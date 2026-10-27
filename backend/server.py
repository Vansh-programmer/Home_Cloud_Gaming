"""
Main Backend HTTP & WebSocket Server (Phase 3+).

Provides:
- Invite-only authentication (login, logout, invite redemption, token verification)
- Game library discovery API
- Single-session GPU lock & Session State Machine API (starting -> ready -> playing -> ended)
- Authenticated WebSocket signaling/input proxy to the internal isolated container
- Admin control API (force-end session, GPU telemetry, user & invite management, session history)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from backend.database import CloudGamingDatabase
from backend.orchestrator import SessionConflictError, SessionOrchestrator
from engine.steam_manager import SteamLibraryManager
from engine.storage_manager import UserStorageManager

logger = logging.getLogger("backend_server")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_COOKIE_NAME = "ryoku_session"


def extract_token(request: web.Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie_token:
        return cookie_token.strip()
    query_token = request.query.get("token", "")
    if query_token:
        return query_token.strip()
    return ""


def get_authenticated_user(request: web.Request, db: CloudGamingDatabase) -> Optional[Dict[str, object]]:
    token = extract_token(request)
    if not token:
        return None
    return db.verify_session_token(token)


def create_orchestrator_app(
    db: CloudGamingDatabase,
    storage_mgr: UserStorageManager,
    steam_mgr: SteamLibraryManager,
    orchestrator: SessionOrchestrator,
) -> web.Application:
    @web.middleware
    async def no_cache_middleware(request: web.Request, handler):
        resp = await handler(request)
        if isinstance(resp, web.StreamResponse):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["CDN-Cache-Control"] = "no-store"
            resp.headers["Pragma"] = "no-cache"
        return resp

    app = web.Application(middlewares=[no_cache_middleware])

    async def on_startup(_app: web.Application) -> None:
        await orchestrator.start()

    async def on_cleanup(_app: web.Application) -> None:
        await orchestrator.stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    web_dir = PROJECT_ROOT / "web"

    def require_user(request: web.Request) -> Dict[str, object]:
        user = get_authenticated_user(request, db)
        if not user:
            raise web.HTTPUnauthorized(
                text=json.dumps({"ok": False, "error": "Authentication required. Please log in."}),
                content_type="application/json",
            )
        return user

    def require_admin(request: web.Request) -> Dict[str, object]:
        user = require_user(request)
        if user.get("role") != "admin":
            raise web.HTTPForbidden(
                text=json.dumps({"ok": False, "error": "Administrator privileges required."}),
                content_type="application/json",
            )
        return user

    # -------------------------------------------------------------------------
    # Public Health & Static UI Routes
    # -------------------------------------------------------------------------

    def is_https_request(request: web.Request) -> bool:
        if request.scheme == "https":
            return True
        xfp = request.headers.get("X-Forwarded-Proto", "").lower()
        return xfp == "https"

    async def handle_health(_request: web.Request) -> web.Response:
        if orchestrator.network_mgr.maintenance_offline_mode:
            return web.json_response(
                {
                    "ok": False,
                    "online": False,
                    "status": "pc_offline",
                    "server_name": "Ryoku Cloud Gaming PC",
                    "in_use": False,
                    "active_session": None,
                    "message": "Gaming PC is currently powered off or in offline maintenance mode.",
                },
                status=503,
            )
        active = orchestrator.get_active_session_public_summary()
        return web.json_response(
            {
                "ok": True,
                "online": True,
                "status": "online",
                "server_name": "Ryoku Cloud Gaming PC",
                "public_domain": orchestrator.network_mgr.public_domain,
                "in_use": active is not None,
                "active_session": active,
            }
        )

    async def handle_index(request: web.Request) -> web.StreamResponse:
        app_html = web_dir / "index.html"
        target_html = app_html if app_html.exists() else (web_dir / "prototype.html")
        if request.path.startswith("/cloudgaming"):
            html_text = target_html.read_text(encoding="utf-8")
            html_text = (
                html_text.replace('href="/assets/', 'href="/cloudgaming/assets/')
                .replace('src="/assets/', 'src="/cloudgaming/assets/')
                .replace('href="/offline"', 'href="/cloudgaming/offline"')
            )
            return web.Response(text=html_text, content_type="text/html")
        return web.FileResponse(target_html)

    async def handle_offline_page(request: web.Request) -> web.StreamResponse:
        offline_html = web_dir / "offline.html"
        if offline_html.exists():
            if request.path.startswith("/cloudgaming"):
                html_text = offline_html.read_text(encoding="utf-8")
                html_text = (
                    html_text.replace('fetch("/api/health"', 'fetch("/cloudgaming/api/health"')
                    .replace('window.location.href = "/"', 'window.location.href = "/cloudgaming"')
                )
                return web.Response(text=html_text, content_type="text/html")
            return web.FileResponse(offline_html)
        return web.Response(text="Gaming PC is currently offline.", status=503)

    async def handle_prototype(_request: web.Request) -> web.StreamResponse:
        return web.FileResponse(web_dir / "prototype.html")

    # -------------------------------------------------------------------------
    # Authentication Routes (Invite-Only)
    # -------------------------------------------------------------------------

    async def handle_login(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON body."}, status=400)

        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not username or not password:
            return web.json_response(
                {"ok": False, "error": "Please enter both username and password."},
                status=400,
            )

        auth = db.authenticate_user(
            username=username,
            password=password,
            user_agent=request.headers.get("User-Agent", ""),
            ip_address=request.remote or "",
        )
        if not auth:
            return web.json_response(
                {"ok": False, "error": "Invalid username or password."},
                status=401,
            )

        storage_mgr.prepare_user_storage(str(auth["username"]))
        resp = web.json_response(
            {
                "ok": True,
                "token": auth["token"],
                "user": {
                    "username": auth["username"],
                    "role": auth["role"],
                },
            }
        )
        resp.set_cookie(
            SESSION_COOKIE_NAME,
            str(auth["token"]),
            max_age=7 * 24 * 3600,
            httponly=True,
            secure=is_https_request(request),
            samesite="Lax",
            path="/",
        )
        return resp

    async def handle_redeem_invite(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON body."}, status=400)

        invite_code = str(body.get("invite_code", body.get("code", ""))).strip()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))

        if not invite_code:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Public sign-up is disabled. A valid invite code is required.",
                },
                status=403,
            )

        try:
            user = db.redeem_invite(code=invite_code, username=username, password=password)
        except ValueError as exc:
            msg = str(exc)
            status = 403 if "invite" in msg.lower() else 400
            return web.json_response({"ok": False, "error": msg}, status=status)

        storage_mgr.prepare_user_storage(str(user["username"]))
        token_info = db.issue_token_for_user(
            username=str(user["username"]),
            user_agent=request.headers.get("User-Agent", ""),
            ip_address=request.remote or "",
        )
        resp = web.json_response(
            {
                "ok": True,
                "token": token_info["token"],
                "user": {
                    "username": user["username"],
                    "role": user["role"],
                },
            }
        )
        resp.set_cookie(
            SESSION_COOKIE_NAME,
            str(token_info["token"]),
            max_age=7 * 24 * 3600,
            httponly=True,
            secure=is_https_request(request),
            samesite="Lax",
            path="/",
        )
        return resp

    async def handle_logout(request: web.Request) -> web.Response:
        token = extract_token(request)
        if token:
            db.revoke_session_token(token)
        resp = web.json_response({"ok": True})
        resp.del_cookie(SESSION_COOKIE_NAME, path="/")
        return resp

    async def handle_me(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        steam_status = storage_mgr.get_user_steam_status(uname)
        my_session = orchestrator.get_session_for_user(uname)
        active_summary = orchestrator.get_active_session_public_summary()
        return web.json_response(
            {
                "ok": True,
                "user": {
                    "username": uname,
                    "role": user["role"],
                    "steam_login_remembered": steam_status["steam_login_remembered"],
                    "steam_account_hint": steam_status["steam_account_hint"],
                    "cyberarena_save": steam_status["cyberarena_save"],
                },
                "active_session": active_summary,
                "my_session": my_session,
            }
        )

    # -------------------------------------------------------------------------
    # Game Library & Session Orchestration Routes
    # -------------------------------------------------------------------------

    async def handle_list_games(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        steam_status = storage_mgr.get_user_steam_status(uname)
        games = [g.to_dict() for g in steam_mgr.list_games(include_builtins=True)]
        return web.json_response(
            {
                "ok": True,
                "games": games,
                "user_storage": steam_status,
            }
        )

    async def handle_get_game_launch_options(request: web.Request) -> web.Response:
        require_user(request)
        app_id = request.match_info.get("app_id", "0")
        opts = steam_mgr.get_custom_launch_options(app_id) or ""
        return web.json_response({"ok": True, "app_id": app_id, "launch_options": opts})

    async def handle_set_game_launch_options(request: web.Request) -> web.Response:
        require_user(request)
        app_id = request.match_info.get("app_id", "0")
        try:
            body = await request.json()
        except Exception:
            body = {}
        opts = str(body.get("launch_options", "")).strip()
        steam_mgr.set_custom_launch_options(app_id, opts)
        return web.json_response({"ok": True, "app_id": app_id, "launch_options": opts})

    async def handle_server_status(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        active = orchestrator.get_active_session_public_summary()
        my_session = orchestrator.get_session_for_user(uname)
        is_online = not orchestrator.network_mgr.maintenance_offline_mode
        has_my_active = my_session is not None and my_session.get("state") in ("starting", "ready", "playing")
        slots_full = len([s for s in orchestrator.active_sessions.values() if s.state != "ended"]) >= orchestrator.max_concurrent_sessions
        busy_by_other = (active is not None and not has_my_active) if orchestrator.max_concurrent_sessions == 1 else (slots_full and not has_my_active)
        return web.json_response(
            {
                "ok": True,
                "online": is_online,
                "in_use": active is not None,
                "busy_by_other": busy_by_other,
                "active_session": active,
                "my_session": my_session,
            }
        )

    async def handle_webrtc_ice_config(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        return web.json_response(orchestrator.network_mgr.get_client_ice_config(uname))

    async def handle_session_start(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        try:
            body = await request.json()
        except Exception:
            body = {}

        app_id = str(body.get("app_id", "0")).strip() or "0"
        quality = str(body.get("quality", "high")).strip() or "high"
        width = int(body.get("width", 1280))
        height = int(body.get("height", 720))
        fps = int(body.get("fps", 60))
        launch_opts = str(body.get("launch_options", "")).strip() or None

        try:
            session_dict = await orchestrator.start_or_reconnect_session(
                username=uname,
                app_id=app_id,
                quality=quality,
                width=width,
                height=height,
                fps=fps,
                launch_options=launch_opts,
            )
            return web.json_response({"ok": True, "session": session_dict})
        except SessionConflictError as exc:
            return web.json_response(
                {
                    "ok": False,
                    "code": "SERVER_BUSY",
                    "active_username": exc.active_username,
                    "active_game": exc.active_game,
                    "error": str(exc),
                },
                status=409,
            )
        except Exception as exc:
            logger.exception("Failed to start session for %s: %s", uname, exc)
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_session_current(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        my_session = orchestrator.get_session_for_user(uname)
        active = orchestrator.get_active_session_public_summary()
        has_my_active = my_session is not None and my_session.get("state") in ("starting", "ready", "playing")
        slots_full = len([s for s in orchestrator.active_sessions.values() if s.state != "ended"]) >= orchestrator.max_concurrent_sessions
        busy_by_other = (active is not None and not has_my_active) if orchestrator.max_concurrent_sessions == 1 else (slots_full and not has_my_active)
        return web.json_response(
            {
                "ok": True,
                "session": my_session,
                "active_session": active,
                "busy_by_other": busy_by_other,
            }
        )

    async def handle_session_quality(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        s = orchestrator.get_managed_session_by_user(uname)
        if not s or s.state == "ended":
            return web.json_response(
                {"ok": False, "error": "No active session found for your account."},
                status=404,
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        quality = str(body.get("quality", "high"))
        s.quality = quality
        async with ClientSession(timeout=ClientTimeout(total=2.0)) as client:
            try:
                async with client.post(
                    f"{s.internal_http_url}/api/session/quality",
                    json={"quality": quality},
                ) as resp:
                    data = await resp.json()
                    return web.json_response(data, status=resp.status)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=502)

    async def handle_session_stop(request: web.Request) -> web.Response:
        user = require_user(request)
        uname = str(user["username"])
        try:
            ended = await orchestrator.terminate_session(
                reason="user_quit",
                expected_username=uname,
            )
        except PermissionError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=403)
        return web.json_response({"ok": True, "session": ended})

    async def handle_session_ws_proxy(request: web.Request) -> web.WebSocketResponse:
        """
        Authenticated WebSocket proxy to the user's isolated session container.
        Enforces strict session ownership so User B can never view or send inputs to User A's game.
        """
        user = get_authenticated_user(request, db)
        if not user:
            raise web.HTTPUnauthorized(text="Unauthorized WebSocket connection")

        uname = str(user["username"])
        s = orchestrator.get_managed_session_by_user(uname)
        if s is None or s.state == "ended":
            # If an active session exists on the PC belonging to another player, return 403 Forbidden
            if orchestrator.active_session and orchestrator.active_session.username != uname:
                raise web.HTTPForbidden(text="Cannot connect to another user's gaming session")
            raise web.HTTPNotFound(text="No active gaming session")
        if s.username != uname:
            raise web.HTTPForbidden(text="Cannot connect to another user's gaming session")

        client_ws = web.WebSocketResponse(heartbeat=15.0)
        await client_ws.prepare(request)

        session_id = s.session_id
        # Wait up to 12s if the container's internal HTTP/WS server is still starting up
        inner_ws = None
        async with ClientSession() as proxy_session:
            for _ in range(60):
                if s.session_id not in orchestrator.active_sessions or s.state == "ended":
                    await client_ws.send_json(
                        {"type": "error", "error": "Session ended before stream connected."}
                    )
                    await client_ws.close()
                    return client_ws
                try:
                    inner_ws = await proxy_session.ws_connect(s.internal_ws_url, heartbeat=15.0)
                    break
                except Exception:
                    await asyncio.sleep(0.2)

            if inner_ws is None:
                await client_ws.send_json(
                    {"type": "error", "error": "Timed out connecting to isolated container stream."}
                )
                await client_ws.close()
                return client_ws

            orchestrator.notify_client_ws_connected(session_id)

            async def forward_client_to_inner() -> None:
                try:
                    async for msg in client_ws:
                        if msg.type == WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                mtype = payload.get("type", "")
                                if mtype not in ("answer", "ice", "ping"):
                                    orchestrator.notify_client_input(session_id)
                            except Exception:
                                pass
                            if not inner_ws.closed:
                                await inner_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            orchestrator.notify_client_input(session_id)
                            if not inner_ws.closed:
                                await inner_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                finally:
                    if not inner_ws.closed:
                        await inner_ws.close()

            async def forward_inner_to_client() -> None:
                try:
                    async for msg in inner_ws:
                        if msg.type == WSMsgType.TEXT:
                            if not client_ws.closed:
                                await client_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            if not client_ws.closed:
                                await client_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                finally:
                    if not client_ws.closed:
                        await client_ws.close()

            try:
                await asyncio.gather(
                    forward_client_to_inner(),
                    forward_inner_to_client(),
                    return_exceptions=True,
                )
            finally:
                orchestrator.notify_client_ws_disconnected(session_id)
                if not inner_ws.closed:
                    await inner_ws.close()
                if not client_ws.closed:
                    await client_ws.close()

        return client_ws

    # -------------------------------------------------------------------------
    # Admin Dashboard Routes (role == "admin" strictly enforced)
    # -------------------------------------------------------------------------

    async def handle_admin_overview(request: web.Request) -> web.Response:
        require_admin(request)
        users = db.list_users()
        for u in users:
            st = storage_mgr.get_user_steam_status(str(u["username"]))
            u["steam_login_remembered"] = st["steam_login_remembered"]
            u["steam_account_hint"] = st["steam_account_hint"]
            u["cyberarena_save"] = st["cyberarena_save"]

        active_dict = (
            orchestrator.active_session.to_dict(
                orchestrator.idle_timeout_sec, orchestrator.disconnect_grace_sec
            )
            if orchestrator.active_session and orchestrator.active_session.state != "ended"
            else None
        )
        return web.json_response(
            {
                "ok": True,
                "active_session": active_dict,
                "gpu": orchestrator.sample_gpu_telemetry(),
                "gpu_history": orchestrator.gpu_history,
                "host": orchestrator.get_host_telemetry(),
                "settings": {
                    "idle_timeout_sec": orchestrator.idle_timeout_sec,
                    "disconnect_grace_sec": orchestrator.disconnect_grace_sec,
                },
                "network": orchestrator.network_mgr.get_network_status(),
                "users": users,
                "invites": db.list_invites(),
                "session_history": db.list_session_history(limit=100),
            }
        )

    async def handle_admin_network(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        updated = orchestrator.network_mgr.update_config(body if isinstance(body, dict) else {})
        return web.json_response({"ok": True, "network": updated})

    async def handle_admin_force_stop(request: web.Request) -> web.Response:
        require_admin(request)
        ended = await orchestrator.terminate_session(reason="admin_force_ended")
        return web.json_response({"ok": True, "ended_session": ended})

    async def handle_admin_settings(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        idle_val = body.get("idle_timeout_sec")
        disc_val = body.get("disconnect_grace_sec")
        updated = orchestrator.update_safety_settings(
            idle_timeout_sec=float(idle_val) if idle_val is not None else None,
            disconnect_grace_sec=float(disc_val) if disc_val is not None else None,
        )
        return web.json_response({"ok": True, "settings": updated})

    async def handle_admin_create_user(request: web.Request) -> web.Response:
        require_admin(request)
        try:
            body = await request.json()
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            role = str(body.get("role", "player")).strip() or "player"
            user = db.create_user(username=username, password=password, role=role)
            storage_mgr.prepare_user_storage(str(user["username"]))
            return web.json_response({"ok": True, "user": user})
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def handle_admin_update_user(request: web.Request) -> web.Response:
        admin_user = require_admin(request)
        target_username = request.match_info.get("username", "").strip().lower()
        try:
            body = await request.json()
        except Exception:
            body = {}

        if "active" in body:
            active_flag = bool(body["active"])
            if not active_flag and target_username == str(admin_user["username"]).lower():
                return web.json_response(
                    {"ok": False, "error": "You cannot suspend your own admin account."},
                    status=400,
                )
            if not active_flag and (
                orchestrator.active_session
                and orchestrator.active_session.username == target_username
            ):
                await orchestrator.terminate_session(reason="admin_force_ended")
            if not db.set_user_active(target_username, active_flag):
                return web.json_response({"ok": False, "error": "User not found."}, status=404)

        if "password" in body and body["password"]:
            try:
                if not db.update_user_password(target_username, str(body["password"])):
                    return web.json_response({"ok": False, "error": "User not found."}, status=404)
            except ValueError as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)

        updated_user = db.get_user(target_username)
        return web.json_response({"ok": True, "user": updated_user})

    async def handle_admin_clear_history(request: web.Request) -> web.Response:
        require_admin(request)
        cleared = db.clear_ended_session_history()
        return web.json_response({"ok": True, "cleared_count": cleared})

    async def handle_admin_delete_user(request: web.Request) -> web.Response:
        admin_user = require_admin(request)
        target_username = request.match_info.get("username", "").strip().lower()
        if target_username == str(admin_user["username"]).lower():
            return web.json_response(
                {"ok": False, "error": "You cannot delete your own admin account."},
                status=400,
            )
        # If the user is currently playing, force-end their session first
        if (
            orchestrator.active_session
            and orchestrator.active_session.username == target_username
        ):
            await orchestrator.terminate_session(reason="admin_force_ended")

        deleted = db.delete_user(target_username)
        if not deleted:
            return web.json_response({"ok": False, "error": "User not found."}, status=404)
        return web.json_response({"ok": True, "deleted": target_username})

    async def handle_admin_create_invite(request: web.Request) -> web.Response:
        admin_user = require_admin(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        note = str(body.get("note", ""))
        role = str(body.get("role", "player"))
        ttl_hours = float(body.get("ttl_hours", 168))
        inv = db.create_invite(
            created_by=str(admin_user["username"]),
            note=note,
            role=role,
            ttl_sec=int(ttl_hours * 3600),
        )
        return web.json_response({"ok": True, "invite": inv})

    async def handle_admin_revoke_invite(request: web.Request) -> web.Response:
        require_admin(request)
        code = request.match_info.get("code", "")
        revoked = db.revoke_invite(code)
        return web.json_response({"ok": revoked, "code": code})

    # Register Routes (both root `/` and subpath `/cloudgaming` for vanshdev.online/cloudgaming)
    app.router.add_get("/", handle_index)
    app.router.add_get("/cloudgaming", handle_index)
    app.router.add_get("/cloudgaming/", handle_index)

    if (web_dir / "assets").exists():
        app.router.add_static("/assets", path=web_dir / "assets", show_index=False)
        app.router.add_static("/cloudgaming/assets", path=web_dir / "assets", show_index=False)

    for prefix in ("", "/cloudgaming"):
        app.router.add_get(f"{prefix}/offline", handle_offline_page)
        app.router.add_get(f"{prefix}/prototype", handle_prototype)
        app.router.add_get(f"{prefix}/api/health", handle_health)

        app.router.add_post(f"{prefix}/api/auth/login", handle_login)
        app.router.add_post(f"{prefix}/api/auth/redeem-invite", handle_redeem_invite)
        app.router.add_post(f"{prefix}/api/auth/register", handle_redeem_invite)
        app.router.add_post(f"{prefix}/api/auth/logout", handle_logout)
        app.router.add_get(f"{prefix}/api/auth/me", handle_me)

        app.router.add_get(f"{prefix}/api/games", handle_list_games)
        app.router.add_get(f"{prefix}/api/games/{{app_id}}/launch-options", handle_get_game_launch_options)
        app.router.add_post(f"{prefix}/api/games/{{app_id}}/launch-options", handle_set_game_launch_options)
        app.router.add_get(f"{prefix}/api/server/status", handle_server_status)
        app.router.add_get(f"{prefix}/api/webrtc/ice-config", handle_webrtc_ice_config)
        app.router.add_post(f"{prefix}/api/sessions/start", handle_session_start)
        app.router.add_get(f"{prefix}/api/sessions/current", handle_session_current)
        app.router.add_get(f"{prefix}/api/session/status", handle_session_current)
        app.router.add_post(f"{prefix}/api/sessions/quality", handle_session_quality)
        app.router.add_post(f"{prefix}/api/session/quality", handle_session_quality)
        app.router.add_post(f"{prefix}/api/sessions/stop", handle_session_stop)
        app.router.add_post(f"{prefix}/api/session/stop", handle_session_stop)
        app.router.add_get(f"{prefix}/api/sessions/current/ws", handle_session_ws_proxy)
        app.router.add_get(f"{prefix}/ws", handle_session_ws_proxy)

        app.router.add_get(f"{prefix}/api/admin/overview", handle_admin_overview)
        app.router.add_post(f"{prefix}/api/admin/sessions/force-stop", handle_admin_force_stop)
        app.router.add_post(f"{prefix}/api/admin/settings", handle_admin_settings)
        app.router.add_post(f"{prefix}/api/admin/network", handle_admin_network)
        app.router.add_post(f"{prefix}/api/admin/users", handle_admin_create_user)
        app.router.add_patch(f"{prefix}/api/admin/users/{{username}}", handle_admin_update_user)
        app.router.add_delete(f"{prefix}/api/admin/users/{{username}}", handle_admin_delete_user)
        app.router.add_post(f"{prefix}/api/admin/invites", handle_admin_create_invite)
        app.router.add_delete(f"{prefix}/api/admin/invites/{{code}}", handle_admin_revoke_invite)
        app.router.add_delete(f"{prefix}/api/admin/history", handle_admin_clear_history)

    return app

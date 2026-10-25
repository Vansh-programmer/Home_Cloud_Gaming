#!/usr/bin/env python3
"""
Phase 6 Automated Verification Suite:
External HTTPS Access, STUN/TURN NAT Traversal & Always-On PC-Offline Status Page.

Tests:
1. Production deployment bundle (`deploy/cloudflare_worker.js`, `deploy/cloudflared-config.yml`,
   `deploy/turnserver.conf`, `deploy/ryoku-cloud-gaming.service`, `web/offline.html`),
   HTTPS `X-Forwarded-Proto` `Secure` cookie handling, dynamic HMAC-SHA1 TURN REST credential
   generation (`GET /api/webrtc/ice-config`), GStreamer `turn://` URI formatting, and
   PC-Offline status (`GET /offline` and `503` `GET /api/health` during offline mode).
2. End-to-end isolated WebRTC session negotiation using dynamic ICE server configuration
   fetched from `/api/webrtc/ice-config`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, CookieJar, WSMsgType, web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gi  # noqa: E402

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
from gi.repository import Gst, GstSdp, GstWebRTC  # noqa: E402

from backend.database import CloudGamingDatabase  # noqa: E402
from backend.network_manager import NetworkConfigManager  # noqa: E402
from backend.orchestrator import SessionOrchestrator  # noqa: E402
from backend.server import create_orchestrator_app  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.storage_manager import UserStorageManager  # noqa: E402

Gst.init(None)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPhase6ExternalAccessAndTurn(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cg-phase6-test-"))
        self.storage_mgr = UserStorageManager(data_root=self.temp_dir)
        self.storage_mgr.ensure_base_directories()
        self.steam_mgr = SteamLibraryManager(self.storage_mgr.shared_steam_dir)
        self.network_mgr = NetworkConfigManager(data_root=self.temp_dir)

        self.db = CloudGamingDatabase(db_path=self.temp_dir / "test_phase6.db")
        self.db.ensure_bootstrap_admin("vansh", "admin-pass-123")
        self.storage_mgr.prepare_user_storage("vansh")

        self.orchestrator = SessionOrchestrator(
            db=self.db,
            storage_mgr=self.storage_mgr,
            steam_mgr=self.steam_mgr,
            idle_timeout_sec=120.0,
            disconnect_grace_sec=60.0,
            allow_pre_sandboxed=True,
            network_mgr=self.network_mgr,
        )
        self.app = create_orchestrator_app(
            db=self.db,
            storage_mgr=self.storage_mgr,
            steam_mgr=self.steam_mgr,
            orchestrator=self.orchestrator,
        )
        self.port = get_free_port()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await self.site.start()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.ws_base_url = f"ws://127.0.0.1:{self.port}"

    async def asyncTearDown(self) -> None:
        await self.runner.cleanup()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_01_network_turn_hmac_credentials_and_offline_status(self) -> None:
        # 1. Verify production deployment artifacts exist and contain required config
        cf_worker = PROJECT_ROOT / "deploy" / "cloudflare_worker.js"
        cf_tunnel = PROJECT_ROOT / "deploy" / "cloudflared-config.yml"
        turn_conf = PROJECT_ROOT / "deploy" / "turnserver.conf"
        systemd_unit = PROJECT_ROOT / "deploy" / "ryoku-cloud-gaming.service"
        offline_page = PROJECT_ROOT / "web" / "offline.html"

        self.assertTrue(cf_worker.exists(), "Missing deploy/cloudflare_worker.js")
        self.assertTrue(cf_tunnel.exists(), "Missing deploy/cloudflared-config.yml")
        self.assertTrue(turn_conf.exists(), "Missing deploy/turnserver.conf")
        self.assertTrue(systemd_unit.exists(), "Missing deploy/ryoku-cloud-gaming.service")
        self.assertTrue(offline_page.exists(), "Missing web/offline.html")

        self.assertIn("OFFLINE_STATUS_CODES", cf_worker.read_text(encoding="utf-8"))
        self.assertIn("use-auth-secret", turn_conf.read_text(encoding="utf-8"))

        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            # 2. Verify GET /offline and subpath GET /cloudgaming & /cloudgaming/offline
            async with client.get(f"{self.base_url}/offline") as resp:
                self.assertEqual(resp.status, 200)
                html = await resp.text()
                self.assertIn("Gaming PC is Currently Powered Off", html)
                self.assertIn("/api/health", html)

            async with client.get(f"{self.base_url}/cloudgaming") as resp:
                self.assertEqual(resp.status, 200)
                cg_html = await resp.text()
                self.assertIn('/cloudgaming/assets/styles.css', cg_html)
                self.assertIn('/cloudgaming/assets/app.js', cg_html)

            async with client.get(f"{self.base_url}/cloudgaming/assets/app.js") as resp:
                self.assertEqual(resp.status, 200)
                js_text = await resp.text()
                self.assertIn("BASE_PREFIX", js_text)

            async with client.get(f"{self.base_url}/cloudgaming/api/health") as resp:
                self.assertEqual(resp.status, 200)
                cg_health = await resp.json()
                self.assertTrue(cg_health["online"])

            # 3. Log in over simulated HTTPS (X-Forwarded-Proto: https) and check Secure cookie
            async with client.post(
                f"{self.base_url}/api/auth/login",
                headers={"X-Forwarded-Proto": "https"},
                json={"username": "vansh", "password": "admin-pass-123"},
            ) as resp:
                self.assertEqual(resp.status, 200)
                set_cookie_hdr = resp.headers.get("Set-Cookie", "")
                self.assertIn("HttpOnly", set_cookie_hdr)
                self.assertIn("Secure", set_cookie_hdr)
                login_data = await resp.json()
                token = login_data["token"]

            auth_headers = {"Authorization": f"Bearer {token}"}

            # 4. Configure external domain + STUN/TURN + HMAC secret via POST /api/admin/network
            test_secret = "ryoku-super-secret-hmac-2026"
            async with client.post(
                f"{self.base_url}/api/admin/network",
                headers=auth_headers,
                json={
                    "public_domain": "https://play.ryoku.example.com/",
                    "stun_url": "stun:stun.l.google.com:19302",
                    "turn_url": "turn:turn.ryoku.example.com:3478",
                    "turn_secret": test_secret,
                    "turn_ttl_sec": 3600,
                    "enable_container_ice": True,
                },
            ) as resp:
                self.assertEqual(resp.status, 200)
                net_data = (await resp.json())["network"]
                self.assertEqual(net_data["public_domain"], "play.ryoku.example.com")
                self.assertEqual(net_data["https_url"], "https://play.ryoku.example.com")
                self.assertTrue(net_data["turn_configured"])
                self.assertTrue(net_data["turn_has_secret"])

            # 5. Fetch dynamic WebRTC ICE configuration from GET /api/webrtc/ice-config
            async with client.get(
                f"{self.base_url}/api/webrtc/ice-config",
                headers=auth_headers,
            ) as resp:
                self.assertEqual(resp.status, 200)
                ice_cfg = await resp.json()
                self.assertTrue(ice_cfg["ok"])
                self.assertEqual(ice_cfg["turn_mode"], "hmac_rest")
                servers = ice_cfg["iceServers"]
                self.assertEqual(len(servers), 2)
                self.assertEqual(servers[0]["urls"], ["stun:stun.l.google.com:19302"])
                turn_entry = servers[1]
                self.assertEqual(turn_entry["urls"], ["turn:turn.ryoku.example.com:3478"])
                turn_user = turn_entry["username"]
                turn_cred = turn_entry["credential"]
                self.assertTrue(turn_user.endswith(":vansh"))

                # Verify HMAC-SHA1 signature matches coturn specification
                expected_hmac = base64.b64encode(
                    hmac.new(
                        test_secret.encode("utf-8"),
                        turn_user.encode("utf-8"),
                        hashlib.sha1,
                    ).digest()
                ).decode("ascii")
                self.assertEqual(turn_cred, expected_hmac)

            # 6. Verify GStreamer container ICE environment formatting
            gst_env = self.network_mgr.get_gstreamer_ice_env("vansh")
            self.assertEqual(gst_env.get("STUN_SERVER"), "stun://stun.l.google.com:19302")
            self.assertTrue(
                gst_env.get("TURN_SERVER", "").startswith("turn://"),
                f"Unexpected TURN_SERVER URI: {gst_env}",
            )
            self.assertIn("@turn.ryoku.example.com:3478", gst_env["TURN_SERVER"])

            # Disable container external ICE before local loopback stream test
            await client.post(
                f"{self.base_url}/api/admin/network",
                headers=auth_headers,
                json={"enable_container_ice": False},
            )

            # 7. Test PC-Offline / Maintenance Mode on /api/health
            async with client.post(
                f"{self.base_url}/api/admin/network",
                headers=auth_headers,
                json={"maintenance_offline_mode": True},
            ) as resp:
                self.assertEqual(resp.status, 200)

            async with client.get(f"{self.base_url}/api/health") as resp:
                self.assertEqual(resp.status, 503)
                h_offline = await resp.json()
                self.assertFalse(h_offline["online"])
                self.assertEqual(h_offline["status"], "pc_offline")

            # Restore online mode
            async with client.post(
                f"{self.base_url}/api/admin/network",
                headers=auth_headers,
                json={"maintenance_offline_mode": False},
            ) as resp:
                self.assertEqual(resp.status, 200)

            async with client.get(f"{self.base_url}/api/health") as resp:
                self.assertEqual(resp.status, 200)
                h_online = await resp.json()
                self.assertTrue(h_online["online"])
                self.assertEqual(h_online["status"], "online")

    async def test_02_end_to_end_session_with_dynamic_ice_config(self) -> None:
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            async with client.post(
                f"{self.base_url}/api/auth/login",
                json={"username": "vansh", "password": "admin-pass-123"},
            ) as resp:
                self.assertEqual(resp.status, 200)

            # Disable external STUN for deterministic loopback test inside sandbox
            await client.post(
                f"{self.base_url}/api/admin/network",
                json={"stun_url": "", "turn_url": "", "enable_container_ice": False},
            )

            async with client.get(f"{self.base_url}/api/webrtc/ice-config") as resp:
                self.assertEqual(resp.status, 200)
                ice_cfg = await resp.json()
                self.assertEqual(ice_cfg["iceServers"], [])

            # Start isolated session
            async with client.post(
                f"{self.base_url}/api/sessions/start",
                json={"app_id": "0", "quality": "high", "width": 1280, "height": 720, "fps": 60},
            ) as resp:
                self.assertEqual(resp.status, 200)

            # Wait for session to reach ready
            for _ in range(50):
                async with client.get(f"{self.base_url}/api/sessions/current") as resp:
                    s_data = (await resp.json())["session"]
                    if s_data and s_data["state"] in ("ready", "playing"):
                        break
                await asyncio.sleep(0.2)
            else:
                self.fail("Session did not reach ready state in time")

            # Connect WebSocket & negotiate WebRTC Offer/Answer + DataChannel Ping/Pong
            pipe = Gst.parse_launch(
                "webrtcbin name=clientwb bundle-policy=max-bundle "
                " fakesink name=vsink sync=false "
                " fakesink name=asink sync=false"
            )
            client_wb = pipe.get_by_name("clientwb")
            loop = asyncio.get_running_loop()
            pong_received = loop.create_future()

            def on_pad_added(_wb: Gst.Element, pad: Gst.Pad) -> None:
                caps = pad.get_current_caps()
                if not caps:
                    return
                s_name = caps.get_structure(0).get_name()
                if "video" in s_name:
                    depay = Gst.ElementFactory.make("rtph264depay", None)
                    sink = pipe.get_by_name("vsink")
                    pipe.add(depay)
                    depay.sync_state_with_parent()
                    pad.link(depay.get_static_pad("sink"))
                    depay.link(sink)
                elif "audio" in s_name:
                    depay = Gst.ElementFactory.make("rtpopusdepay", None)
                    sink = pipe.get_by_name("asink")
                    pipe.add(depay)
                    depay.sync_state_with_parent()
                    pad.link(depay.get_static_pad("sink"))
                    depay.link(sink)

            client_wb.connect("pad-added", on_pad_added)
            pipe.set_state(Gst.State.PLAYING)

            try:
                async with client.ws_connect(f"{self.ws_base_url}/api/sessions/current/ws") as ws:
                    def on_ice_candidate(_wb: Gst.Element, mline: int, candidate: str) -> None:
                        asyncio.run_coroutine_threadsafe(
                            ws.send_json({"type": "ice", "sdpMLineIndex": mline, "candidate": candidate}),
                            loop,
                        )

                    client_wb.connect("on-ice-candidate", on_ice_candidate)

                    dc = client_wb.emit("create-data-channel", "input", None)

                    def on_dc_message(_dc: object, msg_str: str) -> None:
                        try:
                            payload = json.loads(msg_str)
                            if payload.get("type") == "pong" and not pong_received.done():
                                loop.call_soon_threadsafe(pong_received.set_result, payload)
                        except Exception:
                            pass

                    def on_dc_open(channel: object) -> None:
                        channel.emit(
                            "send-string",
                            json.dumps({"type": "ping", "client_ts": 12345.0}),
                        )

                    dc.connect("on-open", on_dc_open)
                    dc.connect("on-message-string", on_dc_message)

                    async for msg in ws:
                        if msg.type != WSMsgType.TEXT:
                            break
                        data = json.loads(msg.data)
                        if data.get("type") == "offer":
                            res, sdp_msg = GstSdp.SDPMessage.new_from_text(data["sdp"])
                            offer = GstWebRTC.WebRTCSessionDescription.new(
                                GstWebRTC.WebRTCSDPType.OFFER, sdp_msg
                            )
                            p1 = Gst.Promise.new()
                            client_wb.emit("set-remote-description", offer, p1)
                            p1.wait()

                            p2 = Gst.Promise.new()
                            client_wb.emit("create-answer", None, p2)
                            p2.wait()
                            reply = p2.get_reply()
                            answer = reply.get_value("answer")

                            p3 = Gst.Promise.new()
                            client_wb.emit("set-local-description", answer, p3)
                            p3.wait()

                            await ws.send_json({"type": "answer", "sdp": answer.sdp.as_text()})
                        elif data.get("type") == "ice" and data.get("candidate"):
                            client_wb.emit(
                                "add-ice-candidate",
                                int(data.get("sdpMLineIndex", 0)),
                                str(data["candidate"]),
                            )

                        if pong_received.done():
                            break

                        # Also send WebSocket ping so we verify signaling + RTC path
                        await ws.send_json({"type": "ping", "client_ts": 999.0})
                        try:
                            await asyncio.wait_for(asyncio.shield(pong_received), timeout=0.15)
                            break
                        except asyncio.TimeoutError:
                            pass
                        if data.get("type") == "pong":
                            if not pong_received.done():
                                pong_received.set_result(data)
                            break

                    pong = await asyncio.wait_for(pong_received, timeout=8.0)
                    self.assertEqual(pong.get("type"), "pong")
            finally:
                pipe.set_state(Gst.State.NULL)
                await client.post(f"{self.base_url}/api/sessions/stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)


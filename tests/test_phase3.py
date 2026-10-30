"""
Phase 3 Automated Verification Suite:
1. Invite-Only Authentication & Access Control:
   - Rejects public registration without an invite code (403 Forbidden).
   - Admin login, single-use invite generation, and invite redemption by a new player.
   - Rejects reusing an already-redeemed invite code (403 Forbidden).
   - Blocks non-admin players from accessing Admin APIs (403 Forbidden).
2. Single-Session GPU Lock, Tab-Close Reconnect & Admin Force-Stop:
   - Alice launches an isolated game session; state transitions starting -> ready -> playing.
   - Bob attempts to launch a game while Alice is playing -> rejected with 409 SERVER_BUSY.
   - Bob attempts to connect to Alice's WebSocket stream -> rejected with 403 Forbidden.
   - Alice closes her WebSocket (simulating tab refresh / network drop) -> container stays alive
     during the reconnect grace window and Alice seamlessly reconnects to the same session_id.
   - Admin force-stops Alice's session -> container is destroyed, end_reason='admin_force_ended'
     is recorded in session_history, and the GPU lock is released.
3. Automatic Idle Timeout Termination:
   - Session with a 2.2s idle timeout automatically terminates when no inputs arrive,
     recording end_reason='idle_timeout' and freeing the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, CookieJar, WSMsgType, web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import CloudGamingDatabase  # noqa: E402
from backend.orchestrator import SessionOrchestrator  # noqa: E402
from backend.server import create_orchestrator_app  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.storage_manager import UserStorageManager  # noqa: E402


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPhase3BackendOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def _start_server(
        self,
        data_root: Path,
        idle_timeout_sec: float = 600.0,
        disconnect_grace_sec: float = 300.0,
    ) -> tuple[int, web.AppRunner, CloudGamingDatabase, SessionOrchestrator]:
        storage_mgr = UserStorageManager(data_root=data_root)
        storage_mgr.ensure_base_directories()
        steam_mgr = SteamLibraryManager(storage_mgr.shared_steam_dir)

        db = CloudGamingDatabase(db_path=data_root / "cloud_gaming.db")
        db.ensure_bootstrap_admin(username="vansh", password="AdminSecretPassword123")
        storage_mgr.prepare_user_storage("vansh")

        orchestrator = SessionOrchestrator(
            db=db,
            storage_mgr=storage_mgr,
            steam_mgr=steam_mgr,
            idle_timeout_sec=idle_timeout_sec,
            disconnect_grace_sec=disconnect_grace_sec,
            allow_pre_sandboxed=True,
            max_concurrent_sessions=1,
        )
        app = create_orchestrator_app(
            db=db,
            storage_mgr=storage_mgr,
            steam_mgr=steam_mgr,
            orchestrator=orchestrator,
        )
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        port = find_free_port()
        site = web.TCPSite(runner, host="127.0.0.1", port=port)
        await site.start()
        return port, runner, db, orchestrator

    async def test_01_invite_only_auth_and_admin_access_control(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p3_auth_") as tmpdir:
            port, runner, _db, _orch = await self._start_server(Path(tmpdir))
            base = f"http://127.0.0.1:{port}"
            try:
                async with ClientSession() as anon:
                    # 1. Public sign-up without an invite code must be strictly blocked (403)
                    async with anon.post(
                        f"{base}/api/auth/register",
                        json={"username": "intruder", "password": "password123"},
                    ) as resp:
                        self.assertEqual(resp.status, 403)
                        data = await resp.json()
                        self.assertFalse(data["ok"])

                    # 2. Invalid invite code must be rejected (403)
                    async with anon.post(
                        f"{base}/api/auth/redeem-invite",
                        json={
                            "invite_code": "RYOKU-FAKE-CODE",
                            "username": "intruder",
                            "password": "password123",
                        },
                    ) as resp:
                        self.assertEqual(resp.status, 403)

                    # 3. Unauthenticated request to /api/games must return 401
                    async with anon.get(f"{base}/api/games") as resp:
                        self.assertEqual(resp.status, 401)

                # 4. Log in as bootstrap admin (vansh) and create an invite code
                async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as admin_client:
                    async with admin_client.post(
                        f"{base}/api/auth/login",
                        json={"username": "vansh", "password": "AdminSecretPassword123"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        login_data = await resp.json()
                        self.assertTrue(login_data["ok"])
                        self.assertEqual(login_data["user"]["role"], "admin")

                    async with admin_client.post(
                        f"{base}/api/admin/invites",
                        json={"note": "Invite for Alice"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        inv_data = await resp.json()
                        invite_code = inv_data["invite"]["code"]
                        self.assertTrue(invite_code.startswith("RYOKU-"))

                # 5. Redeem the invite code as Alice
                async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as alice_client:
                    async with alice_client.post(
                        f"{base}/api/auth/redeem-invite",
                        json={
                            "invite_code": invite_code,
                            "username": "alice",
                            "password": "AlicePassword123",
                        },
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        alice_data = await resp.json()
                        self.assertTrue(alice_data["ok"])
                        self.assertEqual(alice_data["user"]["username"], "alice")
                        self.assertEqual(alice_data["user"]["role"], "player")

                    # Verify Alice can view the game library
                    async with alice_client.get(f"{base}/api/games") as resp:
                        self.assertEqual(resp.status, 200)
                        games_data = await resp.json()
                        self.assertTrue(len(games_data["games"]) >= 2)

                    # Verify Alice (player role) is blocked from Admin APIs (403)
                    async with alice_client.get(f"{base}/api/admin/overview") as resp:
                        self.assertEqual(resp.status, 403)

                # 6. Verify the single-use invite code cannot be reused by a second person
                async with ClientSession() as reuse_client:
                    async with reuse_client.post(
                        f"{base}/api/auth/redeem-invite",
                        json={
                            "invite_code": invite_code,
                            "username": "mallory",
                            "password": "MalloryPassword123",
                        },
                    ) as resp:
                        self.assertEqual(resp.status, 403)
                        err = await resp.json()
                        self.assertIn("already been used", err["error"])
            finally:
                await runner.cleanup()

    async def test_02_single_session_lock_reconnect_and_admin_force_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p3_lock_") as tmpdir:
            port, runner, db, _orch = await self._start_server(
                Path(tmpdir),
                idle_timeout_sec=120.0,
                disconnect_grace_sec=60.0,
            )
            base = f"http://127.0.0.1:{port}"
            db.create_user("alice", "AlicePassword123", role="player")
            db.create_user("bob", "BobPassword123", role="player")

            try:
                async with (
                    ClientSession(cookie_jar=CookieJar(unsafe=True)) as admin_client,
                    ClientSession(cookie_jar=CookieJar(unsafe=True)) as alice_client,
                    ClientSession(cookie_jar=CookieJar(unsafe=True)) as bob_client,
                ):
                    await admin_client.post(
                        f"{base}/api/auth/login",
                        json={"username": "vansh", "password": "AdminSecretPassword123"},
                    )
                    await alice_client.post(
                        f"{base}/api/auth/login",
                        json={"username": "alice", "password": "AlicePassword123"},
                    )
                    await bob_client.post(
                        f"{base}/api/auth/login",
                        json={"username": "bob", "password": "BobPassword123"},
                    )

                    # 1. Alice starts a CyberArena 3D session (app_id="0")
                    async with alice_client.post(
                        f"{base}/api/sessions/start",
                        json={"app_id": "0", "quality": "high"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        start_data = await resp.json()
                        self.assertTrue(start_data["ok"])
                        session_id = start_data["session"]["session_id"]
                        self.assertFalse(start_data["session"]["reconnected"])

                    # 2. Wait for Alice's session to transition from starting -> ready
                    ready_state = None
                    for _ in range(45):
                        async with alice_client.get(f"{base}/api/sessions/current") as resp:
                            cur = await resp.json()
                            st = cur["session"]["state"]
                            if st in ("ready", "playing"):
                                ready_state = st
                                break
                        await asyncio.sleep(0.25)
                    self.assertIn(ready_state, ("ready", "playing"))

                    # 3. Bob tries to launch a game while Alice is playing -> MUST return 409 SERVER_BUSY
                    async with bob_client.post(
                        f"{base}/api/sessions/start",
                        json={"app_id": "0", "quality": "high"},
                    ) as resp:
                        self.assertEqual(resp.status, 409)
                        busy_data = await resp.json()
                        self.assertEqual(busy_data["code"], "SERVER_BUSY")
                        self.assertEqual(busy_data["active_username"], "alice")
                        self.assertIn("alice", busy_data["error"])

                    # 4. Bob tries to connect to Alice's WebSocket stream -> MUST return 403 Forbidden
                    async with bob_client.get(f"{base}/api/sessions/current/ws") as resp:
                        self.assertEqual(resp.status, 403)

                    # 5. Alice connects her WebSocket via the authenticated proxy & receives WebRTC Offer
                    async with alice_client.ws_connect(f"ws://127.0.0.1:{port}/api/sessions/current/ws") as ws:
                        got_offer = False
                        for _ in range(30):
                            msg = await ws.receive(timeout=5.0)
                            self.assertEqual(msg.type, WSMsgType.TEXT)
                            payload = json.loads(msg.data)
                            if payload.get("type") == "offer":
                                got_offer = True
                                break
                        self.assertTrue(got_offer, "Alice must receive WebRTC SDP Offer through proxy")

                        # Verify session state is now 'playing'
                        async with alice_client.get(f"{base}/api/sessions/current") as resp:
                            cur = await resp.json()
                            self.assertEqual(cur["session"]["state"], "playing")
                            self.assertTrue(cur["session"]["client_connected"])

                    # 6. Alice's WebSocket closed (simulating tab close / Wi-Fi drop).
                    # Verify session stays alive in 'ready' state and Alice can seamlessly reconnect!
                    await asyncio.sleep(0.2)
                    async with alice_client.get(f"{base}/api/sessions/current") as resp:
                        cur = await resp.json()
                        self.assertEqual(cur["session"]["state"], "ready")
                        self.assertFalse(cur["session"]["client_connected"])
                        self.assertIsNotNone(cur["session"]["disconnected_at"])

                    async with alice_client.post(
                        f"{base}/api/sessions/start",
                        json={"app_id": "0", "quality": "high"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        recon_data = await resp.json()
                        self.assertTrue(recon_data["session"]["reconnected"])
                        self.assertEqual(recon_data["session"]["session_id"], session_id)

                    # 7. Admin checks /api/admin/overview and force-stops Alice's session
                    async with admin_client.get(f"{base}/api/admin/overview") as resp:
                        self.assertEqual(resp.status, 200)
                        overview = await resp.json()
                        self.assertIsNotNone(overview["active_session"])
                        self.assertEqual(overview["active_session"]["session_id"], session_id)
                        self.assertIn("gpu", overview)

                    async with admin_client.post(f"{base}/api/admin/sessions/force-stop") as resp:
                        self.assertEqual(resp.status, 200)
                        stop_data = await resp.json()
                        self.assertEqual(stop_data["ended_session"]["state"], "ended")
                        self.assertEqual(stop_data["ended_session"]["end_reason"], "admin_force_ended")

                    # Verify Alice sees the friendly admin-ended message
                    async with alice_client.get(f"{base}/api/sessions/current") as resp:
                        cur = await resp.json()
                        self.assertEqual(cur["session"]["state"], "ended")
                        self.assertEqual(cur["session"]["end_reason"], "admin_force_ended")
                        self.assertIn("administrator", cur["session"]["stage_message"])

                    # Verify session history recorded 'admin_force_ended'
                    async with admin_client.get(f"{base}/api/admin/overview") as resp:
                        overview = await resp.json()
                        self.assertIsNone(overview["active_session"])
                        hist = overview["session_history"]
                        self.assertTrue(len(hist) >= 1)
                        self.assertEqual(hist[0]["session_id"], session_id)
                        self.assertEqual(hist[0]["end_reason"], "admin_force_ended")
            finally:
                await runner.cleanup()

    async def test_03_idle_timeout_automatic_termination(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p3_idle_") as tmpdir:
            # Configure a short 2.2s idle timeout for fast automated verification
            port, runner, db, _orch = await self._start_server(
                Path(tmpdir),
                idle_timeout_sec=2.2,
                disconnect_grace_sec=30.0,
            )
            base = f"http://127.0.0.1:{port}"
            db.create_user("alice", "AlicePassword123", role="player")

            try:
                async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as alice_client:
                    await alice_client.post(
                        f"{base}/api/auth/login",
                        json={"username": "alice", "password": "AlicePassword123"},
                    )
                    async with alice_client.post(
                        f"{base}/api/sessions/start",
                        json={"app_id": "0", "quality": "high"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    # Wait for session to become ready, then stay idle until watchdog ends it
                    ended_session = None
                    last_cur = None
                    for _ in range(60):
                        async with alice_client.get(f"{base}/api/sessions/current") as resp:
                            cur = await resp.json()
                            last_cur = cur
                            if cur["session"] and cur["session"]["state"] == "ended":
                                ended_session = cur["session"]
                                break
                        await asyncio.sleep(0.25)

                    if ended_session is None:
                        logs = [
                            p.read_text(encoding="utf-8", errors="ignore")
                            for p in Path(tmpdir).glob("session-*.log")
                        ]
                        self.fail(f"Session did not auto-terminate. last_cur={last_cur}, logs={logs}")
                    self.assertEqual(ended_session["end_reason"], "idle_timeout")
                    self.assertIn("inactivity", ended_session["stage_message"])
            finally:
                await runner.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)

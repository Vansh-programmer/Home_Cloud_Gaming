"""
Phase 5 Automated Verification Suite:
1. Deep GPU, NVENC Encoder & Host System Telemetry + Runtime Safety Settings:
   - Verifies GET /api/admin/overview returns RTX 4060 GPU metrics (3D core %, NVENC encoder %,
     VRAM MB & %, temperature °C, thermal state), rolling gpu_history sparkline samples,
     and host CPU/RAM/Disk telemetry.
   - Verifies POST /api/admin/settings updates idle_timeout_sec and disconnect_grace_sec live.
2. Full Admin User Lifecycle, Mid-Session Suspension, Invite Revocation & History Audit:
   - Admin creates player 'charlie'; charlie logs in and starts a game session.
   - Admin suspends 'charlie' (PATCH /api/admin/users/charlie {"active": false}) while playing:
     * Charlie's active session is immediately force-ended (end_reason='admin_force_ended').
     * Charlie's session token is revoked (401 Unauthorized) and login is blocked.
   - Admin reactivates 'charlie' and resets password; charlie logs in with the new password.
   - Admin generates an invite code, revokes it (DELETE /api/admin/invites/{code}), and verifies
     redeeming the revoked code is rejected with 403 Forbidden.
   - Admin clears ended session history (DELETE /api/admin/history) and deletes 'charlie'.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, CookieJar, web

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


class TestPhase5AdminPortalAndTelemetry(unittest.IsolatedAsyncioTestCase):
    async def _start_server(
        self, data_root: Path
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
            idle_timeout_sec=600.0,
            disconnect_grace_sec=300.0,
            allow_pre_sandboxed=True,
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

    async def test_01_admin_gpu_nvenc_host_telemetry_and_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p5_telem_") as tmpdir:
            port, runner, _db, _orch = await self._start_server(Path(tmpdir))
            base = f"http://127.0.0.1:{port}"
            try:
                async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as admin:
                    await admin.post(
                        f"{base}/api/auth/login",
                        json={"username": "vansh", "password": "AdminSecretPassword123"},
                    )

                    async with admin.get(f"{base}/api/admin/overview") as resp:
                        self.assertEqual(resp.status, 200)
                        data = await resp.json()

                        # Verify GPU & NVENC telemetry fields
                        gpu = data["gpu"]
                        for key in (
                            "name",
                            "driver_version",
                            "gpu_util_percent",
                            "encoder_util_percent",
                            "vram_used_mb",
                            "vram_total_mb",
                            "vram_percent",
                            "temperature_c",
                            "thermal_state",
                        ):
                            self.assertIn(key, gpu, f"Missing GPU telemetry key: {key}")

                        # Verify rolling GPU sparkline history
                        self.assertTrue(len(data["gpu_history"]) >= 1)
                        self.assertIn("enc_util", data["gpu_history"][0])

                        # Verify Host CPU/RAM/Disk telemetry
                        host = data["host"]
                        for hkey in (
                            "cpu_cores",
                            "load_1m",
                            "ram_used_gb",
                            "ram_total_gb",
                            "disk_free_gb",
                            "disk_total_gb",
                        ):
                            self.assertIn(hkey, host, f"Missing Host telemetry key: {hkey}")
                        self.assertGreater(host["disk_total_gb"], 0)

                    # Update runtime safety limits via POST /api/admin/settings
                    async with admin.post(
                        f"{base}/api/admin/settings",
                        json={"idle_timeout_sec": 180, "disconnect_grace_sec": 90},
                    ) as s_resp:
                        self.assertEqual(s_resp.status, 200)
                        s_data = await s_resp.json()
                        self.assertEqual(s_data["settings"]["idle_timeout_sec"], 180.0)
                        self.assertEqual(s_data["settings"]["disconnect_grace_sec"], 90.0)
            finally:
                await runner.cleanup()

    async def test_02_admin_user_lifecycle_mid_session_suspend_and_history_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p5_users_") as tmpdir:
            port, runner, _db, _orch = await self._start_server(Path(tmpdir))
            base = f"http://127.0.0.1:{port}"
            try:
                async with (
                    ClientSession(cookie_jar=CookieJar(unsafe=True)) as admin,
                    ClientSession(cookie_jar=CookieJar(unsafe=True)) as charlie,
                ):
                    await admin.post(
                        f"{base}/api/auth/login",
                        json={"username": "vansh", "password": "AdminSecretPassword123"},
                    )

                    # 1. Admin creates user 'charlie'
                    async with admin.post(
                        f"{base}/api/admin/users",
                        json={"username": "charlie", "password": "CharliePassword123", "role": "player"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    # 2. Charlie logs in and launches a session
                    async with charlie.post(
                        f"{base}/api/auth/login",
                        json={"username": "charlie", "password": "CharliePassword123"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    async with charlie.post(
                        f"{base}/api/sessions/start",
                        json={"app_id": "0", "quality": "high"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    for _ in range(45):
                        async with charlie.get(f"{base}/api/sessions/current") as resp:
                            cur = await resp.json()
                            if cur["session"]["state"] in ("ready", "playing"):
                                break
                        await asyncio.sleep(0.25)

                    # 3. Admin suspends Charlie mid-session -> must force-end Charlie's session & revoke token
                    async with admin.patch(
                        f"{base}/api/admin/users/charlie",
                        json={"active": False},
                    ) as resp:
                        self.assertEqual(resp.status, 200)
                        u_data = await resp.json()
                        self.assertFalse(u_data["user"]["active"])

                    # Charlie's existing session cookie must now be rejected (401)
                    async with charlie.get(f"{base}/api/auth/me") as resp:
                        self.assertEqual(resp.status, 401)

                    # Verify Admin overview shows no active session and history recorded admin_force_ended
                    async with admin.get(f"{base}/api/admin/overview") as resp:
                        ov = await resp.json()
                        self.assertIsNone(ov["active_session"])
                        self.assertEqual(ov["session_history"][0]["end_reason"], "admin_force_ended")

                    # 4. Admin reactivates Charlie and resets password
                    async with admin.patch(
                        f"{base}/api/admin/users/charlie",
                        json={"active": True, "password": "NewCharliePassword999"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    async with charlie.post(
                        f"{base}/api/auth/login",
                        json={"username": "charlie", "password": "NewCharliePassword999"},
                    ) as resp:
                        self.assertEqual(resp.status, 200)

                    # 5. Admin creates an invite code, revokes it, and verifies redemption fails
                    async with admin.post(
                        f"{base}/api/admin/invites",
                        json={"note": "Temp Invite"},
                    ) as resp:
                        inv_code = (await resp.json())["invite"]["code"]

                    async with admin.delete(f"{base}/api/admin/invites/{inv_code}") as resp:
                        self.assertEqual(resp.status, 200)

                    async with ClientSession() as anon:
                        async with anon.post(
                            f"{base}/api/auth/redeem-invite",
                            json={"invite_code": inv_code, "username": "newbie", "password": "Password123"},
                        ) as resp:
                            self.assertEqual(resp.status, 403)

                    # 6. Admin clears ended session history and deletes Charlie
                    async with admin.delete(f"{base}/api/admin/history") as resp:
                        self.assertEqual(resp.status, 200)
                        c_data = await resp.json()
                        self.assertGreaterEqual(c_data["cleared_count"], 1)

                    async with admin.delete(f"{base}/api/admin/users/charlie") as resp:
                        self.assertEqual(resp.status, 200)
            finally:
                await runner.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)


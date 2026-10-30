import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from backend.database import CloudGamingDatabase
from backend.orchestrator import SessionOrchestrator
from backend.server import create_orchestrator_app
from engine.steam_manager import SteamLibraryManager
from engine.storage_manager import UserStorageManager


class TestMoonlightClientIntegration(AioHTTPTestCase):
    async def get_application(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ryoku-client-test-"))
        self.storage_mgr = UserStorageManager(data_root=self.temp_dir)
        self.storage_mgr.ensure_base_directories()
        self.steam_mgr = SteamLibraryManager(self.storage_mgr.shared_steam_dir)
        self.db = CloudGamingDatabase(db_path=self.temp_dir / "test.db")
        self.db.ensure_bootstrap_admin("vansh", "password123")
        self.storage_mgr.prepare_user_storage("vansh")

        self.orchestrator = SessionOrchestrator(
            db=self.db,
            storage_mgr=self.storage_mgr,
            steam_mgr=self.steam_mgr,
            max_concurrent_sessions=2,
        )

        return create_orchestrator_app(
            db=self.db,
            storage_mgr=self.storage_mgr,
            steam_mgr=self.steam_mgr,
            orchestrator=self.orchestrator,
        )

    async def test_01_client_endpoint(self):
        resp = await self.client.get("/api/client/endpoint")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("recommended_host", data)
        self.assertIn("tailscale_ip", data)
        self.assertIn("sunshine_port", data)

    async def test_02_download_scripts_target_host_injection(self):
        # Fedora script download
        resp_fedora = await self.client.get("/api/client/download/fedora")
        self.assertEqual(resp_fedora.status, 200)
        text_fedora = await resp_fedora.text()
        self.assertIn("has_webkit", text_fedora)
        self.assertNotIn("__TARGET_HOST__", text_fedora)
        self.assertIn("100.89.198.41", text_fedora)

        # Linux script download
        resp_linux = await self.client.get("/api/client/download/linux")
        self.assertEqual(resp_linux.status, 200)
        text_linux = await resp_linux.text()
        self.assertNotIn("__TARGET_HOST__", text_linux)

        # Windows bat download
        resp_win = await self.client.get("/api/client/download/windows")
        self.assertEqual(resp_win.status, 200)
        text_win = await resp_win.text()
        self.assertNotIn("__TARGET_HOST__", text_win)

    async def test_03_pair_endpoint_validation(self):
        resp = await self.client.post("/api/client/pair", json={"pin": "12"})
        self.assertIn(resp.status, (400, 401))


if __name__ == "__main__":
    unittest.main()

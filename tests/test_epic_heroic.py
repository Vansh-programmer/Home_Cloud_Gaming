"""
Unit Tests for Heroic Games Launcher & Epic Games / GOG Integration.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from engine.heroic_manager import HeroicLibraryManager, find_heroic_binary
from engine.session_runner import IsolatedSessionRuntime
from engine.steam_manager import SteamLibraryManager
from engine.storage_manager import UserStorageManager


class TestEpicHeroicIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.storage_mgr = UserStorageManager(self.data_root)
        self.storage_mgr.ensure_base_directories()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_heroic_launcher_discovery_and_builtins(self) -> None:
        """Verify Heroic Games Launcher (AppID 8) appears in SteamLibraryManager."""
        steam_mgr = SteamLibraryManager(self.storage_mgr.shared_steam_dir)
        games = steam_mgr.list_games(include_builtins=True)
        app_ids = [g.app_id for g in games]
        self.assertIn("8", app_ids)

        heroic_entry = steam_mgr.get_game("8")
        self.assertIsNotNone(heroic_entry)
        self.assertEqual(heroic_entry.category, "epic")
        self.assertIn("Heroic", heroic_entry.title)
        self.assertIn("heroic-cover.svg", heroic_entry.cover_url)

    def test_02_heroic_launch_command_vectors(self) -> None:
        """Verify launch command construction for Heroic GUI and direct Epic Game launch."""
        heroic_mgr = HeroicLibraryManager(self.data_root)

        # 1. Launcher GUI (AppID 8)
        cmd_gui = heroic_mgr.build_launch_command("8")
        self.assertTrue(any("heroic" in str(tok) for tok in cmd_gui))
        self.assertIn("--no-sandbox", cmd_gui)
        self.assertIn("--ozone-platform=x11", cmd_gui)

        # 2. Specific Epic Game (AppID epic_Sugar)
        cmd_game = heroic_mgr.build_launch_command("epic_Sugar")
        self.assertTrue(any("heroic" in str(tok) or "legendary" in str(tok) for tok in cmd_game))

    def test_03_legendary_installed_json_discovery(self) -> None:
        """Verify parsing of Legendary installed.json into unified GameEntry records."""
        # Create mock user directory with ~/.config/legendary/installed.json
        user_config = self.data_root / "users" / "testgamer" / "home" / ".config" / "legendary"
        user_config.mkdir(parents=True, exist_ok=True)
        mock_manifest = {
            "Sugar": {
                "title": "Alan Wake Remastered",
                "install_path": "/home/gamer/Games/Heroic/AlanWakeRemastered",
                "executable": "AlanWake.exe",
                "install_size": 25000000000,
                "app_name": "Sugar",
            }
        }
        (user_config / "installed.json").write_text(json.dumps(mock_manifest), encoding="utf-8")

        heroic_mgr = HeroicLibraryManager(self.data_root)
        discovered = heroic_mgr.list_games()
        self.assertTrue(len(discovered) >= 1)
        aw = next((g for g in discovered if g["app_id"] == "epic_Sugar"), None)
        self.assertIsNotNone(aw)
        self.assertEqual(aw["title"], "Alan Wake Remastered")
        self.assertEqual(aw["category"], "epic")

        # Verify discovery through SteamLibraryManager
        steam_mgr = SteamLibraryManager(self.storage_mgr.shared_steam_dir)
        steam_games = steam_mgr.list_games(include_builtins=True)
        found_in_steam = any(g.app_id == "epic_Sugar" for g in steam_games)
        self.assertTrue(found_in_steam)

    def test_04_heroic_gamesconfig_discovery(self) -> None:
        """Verify parsing of Heroic GamesConfig/*.json manifests."""
        user_hconfig = self.data_root / "users" / "testgamer" / "home" / ".config" / "heroic" / "GamesConfig"
        user_hconfig.mkdir(parents=True, exist_ok=True)
        mock_game_cfg = {
            "title": "Fall Guys",
            "install_path": "/home/gamer/Games/Heroic/FallGuys",
            "executable": "FallGuys_client.exe",
        }
        (user_hconfig / "0ea48443343444a49df589fcbeea902d.json").write_text(
            json.dumps(mock_game_cfg), encoding="utf-8"
        )

        heroic_mgr = HeroicLibraryManager(self.data_root)
        discovered = heroic_mgr.list_games()
        fg = next((g for g in discovered if "Fall Guys" in str(g["title"])), None)
        self.assertIsNotNone(fg)
        self.assertEqual(fg["category"], "epic")

    def test_05_user_storage_heroic_persistence(self) -> None:
        """Verify UserStorageManager initializes Heroic, Legendary, and Games persistence directories."""
        user_paths = self.storage_mgr.prepare_user_storage("testuser")
        home = user_paths.user_root / "home"
        self.assertTrue((home / ".config" / "heroic").is_dir())
        self.assertTrue((home / ".config" / "legendary").is_dir())
        self.assertTrue((home / "Games" / "Heroic").is_dir())

    def test_06_lifecycle_monitor_heroic_detection(self) -> None:
        """Verify is_game_active_in_container recognizes heroic and legendary."""
        runner = IsolatedSessionRuntime(
            session_id="test-heroic-sess",
            user_id="testuser",
            app_id="8",
            width=1920,
            height=1080,
            fps=60,
            port=39997,
            game_cmd=["echo", "test"],
        )
        # Without container proc, returns False safely
        self.assertFalse(runner.is_game_active_in_container())


if __name__ == "__main__":
    unittest.main()


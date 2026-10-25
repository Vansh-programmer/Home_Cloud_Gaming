"""
Phase 2 Automated Verification Suite:
1. Per-user storage isolation, path-traversal protection, shared Steam library symlink syncing,
   and Steam loginusers.vdf session-token detection (without storing passwords).
2. Steam .acf manifest parsing, redistributable/Proton filtering, and isolated GamepadUI launch command generation.
3. End-to-end multi-user persistent savegame verification across ephemeral container restarts:
   - Session 1 (alice): starts at high_score=0, fires laser to score 250, quits game -> container wiped, save persists.
   - Session 2 (alice): starts in a fresh ephemeral container, immediately loads high_score=250 & sessions_played=2.
   - Session 3 (bob): starts in a fresh ephemeral container for bob, verifies strict isolation (high_score=0, sessions_played=1).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, WSMsgType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.sandbox import EphemeralSandbox, SandboxConfig  # noqa: E402
from engine.steam_manager import SteamLibraryManager, parse_acf_manifest  # noqa: E402
from engine.storage_manager import UserStorageManager, validate_user_id  # noqa: E402


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPhase2SteamAndStorage(unittest.IsolatedAsyncioTestCase):
    def test_01_user_storage_isolation_and_steam_token_detection(self) -> None:
        # 1. Verify strict username validation blocks path traversal
        for invalid in ["", "a", "../etc", "../../root", "user/name", "user name", "-bad"]:
            with self.assertRaises(ValueError, msg=f"Should reject invalid user_id: {invalid!r}"):
                validate_user_id(invalid)

        self.assertEqual(validate_user_id("Vansh_01"), "vansh_01")

        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p2_storage_") as tmpdir:
            mgr = UserStorageManager(data_root=Path(tmpdir))

            # Create fake shared Steam game manifest and directory in shared_steam_library
            shared_steamapps = mgr.shared_steam_dir / "steamapps"
            (shared_steamapps / "common" / "Hollow Knight").mkdir(parents=True, exist_ok=True)
            acf_path = shared_steamapps / "appmanifest_367520.acf"
            acf_path.write_text(
                '"AppState"\n{\n'
                '    "appid"      "367520"\n'
                '    "Universe"   "1"\n'
                '    "name"       "Hollow Knight"\n'
                '    "StateFlags" "4"\n'
                '    "installdir" "Hollow Knight"\n'
                '    "SizeOnDisk" "9542041600"\n'
                '}\n',
                encoding="utf-8",
            )

            alice_paths = mgr.prepare_user_storage("alice")
            bob_paths = mgr.prepare_user_storage("bob")
            self.assertNotEqual(alice_paths.user_root, bob_paths.user_root)

            # Verify shared manifest and install directory are linked into alice's steamapps pointing to /steam_shared
            linked_acf = alice_paths.steam_dir / "steam" / "steamapps" / "appmanifest_367520.acf"
            linked_common = alice_paths.steam_dir / "steam" / "steamapps" / "common" / "Hollow Knight"
            self.assertTrue(linked_acf.is_symlink())
            self.assertEqual(os.readlink(linked_acf), "/steam_shared/steamapps/appmanifest_367520.acf")
            self.assertTrue(linked_common.is_symlink())
            self.assertEqual(os.readlink(linked_common), "/steam_shared/steamapps/common/Hollow Knight")

            # Verify libraryfolders.vdf includes /steam_shared
            vdf_file = alice_paths.steam_dir / "steam" / "steamapps" / "libraryfolders.vdf"
            self.assertTrue(vdf_file.exists())
            self.assertIn("/steam_shared", vdf_file.read_text(encoding="utf-8"))

            # Verify Steam login token detection (initially false)
            status_before = mgr.get_user_storage_status("alice")
            self.assertFalse(status_before["steam_login_remembered"])
            self.assertIsNone(status_before["steam_account_name"])

            # Simulate Steam writing loginusers.vdf inside alice's isolated .steam directory
            config_dir = alice_paths.steam_dir / "steam" / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "loginusers.vdf").write_text(
                '"users"\n{\n'
                '    "76561198000000001"\n'
                '    {\n'
                '        "AccountName"      "alice_steam"\n'
                '        "PersonaName"      "AliceGamer"\n'
                '        "RememberPassword" "1"\n'
                '        "MostRecent"       "1"\n'
                '    }\n'
                '}\n',
                encoding="utf-8",
            )

            status_after = mgr.get_user_storage_status("alice")
            self.assertTrue(status_after["steam_login_remembered"])
            self.assertEqual(status_after["steam_account_name"], "alice_steam")
            self.assertEqual(status_after["steam_persona_name"], "AliceGamer")

            # Verify bob still has no Steam login remembered
            bob_status = mgr.get_user_storage_status("bob")
            self.assertFalse(bob_status["steam_login_remembered"])

            # Verify SandboxConfig binds alice's directories and shared_steam_dir read-only
            sb_cfg = SandboxConfig(
                session_id="p2-bind-check",
                user_id="alice",
                shared_steam_dir=alice_paths.shared_steam_dir,
                user_steam_dir=alice_paths.steam_dir,
                user_local_share_dir=alice_paths.local_share_dir,
                user_config_dir=alice_paths.config_dir,
            )
            sb = EphemeralSandbox(sb_cfg)
            sb.prepare_directories()
            try:
                cmd_str = " ".join(sb.build_bwrap_command(["/usr/bin/true"]))
                self.assertIn(f"--ro-bind {alice_paths.shared_steam_dir} /steam_shared", cmd_str)
                self.assertIn(f"--bind {alice_paths.steam_dir} /home/gamer/.steam", cmd_str)
                self.assertIn(f"--bind {alice_paths.local_share_dir} /home/gamer/.local/share", cmd_str)
                self.assertIn(f"--bind {alice_paths.config_dir} /home/gamer/.config", cmd_str)
                self.assertNotIn("/home/vansh", cmd_str.replace(str(PROJECT_ROOT), "").replace(tmpdir, ""))
            finally:
                sb.cleanup()

    def test_02_steam_library_acf_parser_and_launch_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p2_steam_") as tmpdir:
            shared_dir = Path(tmpdir) / "shared_steam"
            steamapps = shared_dir / "steamapps"
            steamapps.mkdir(parents=True, exist_ok=True)

            # 1. Valid playable Steam game
            (steamapps / "appmanifest_620.acf").write_text(
                '"AppState"\n{\n'
                '    "appid"      "620"\n'
                '    "name"       "Portal 2"\n'
                '    "StateFlags" "4"\n'
                '    "installdir" "Portal 2"\n'
                '    "SizeOnDisk" "11811160064"\n'
                '}\n',
                encoding="utf-8",
            )
            # 2. Proton runtime redistributable (must be filtered out of the game library)
            (steamapps / "appmanifest_1493710.acf").write_text(
                '"AppState"\n{\n'
                '    "appid"      "1493710"\n'
                '    "name"       "Proton Experimental"\n'
                '    "StateFlags" "4"\n'
                '    "installdir" "Proton - Experimental"\n'
                '    "SizeOnDisk" "3100000000"\n'
                '}\n',
                encoding="utf-8",
            )

            lib = SteamLibraryManager(shared_steam_dir=shared_dir)
            games = lib.discover_games(include_builtins=True)
            app_ids = [g.app_id for g in games]

            self.assertIn("0", app_ids, "Built-in CyberArena 3D must be present")
            self.assertIn("7", app_ids, "Built-in Steam Big Picture Login must be present")
            self.assertIn("620", app_ids, "Portal 2 must be discovered from appmanifest_620.acf")
            self.assertNotIn("1493710", app_ids, "Proton Experimental must be filtered out of playable games")

            # Verify launch commands
            cmd_builtin = lib.build_launch_command("0")
            self.assertTrue(cmd_builtin[0].endswith("arena3d"))

            cmd_steam_ui = lib.build_launch_command("7")
            self.assertEqual(cmd_steam_ui[0], "/usr/bin/steam")
            self.assertIn("-gamepadui", cmd_steam_ui)

            cmd_portal = lib.build_launch_command("620")
            self.assertEqual(cmd_portal[0], "/usr/bin/steam")
            self.assertIn("-applaunch", cmd_portal)
            self.assertIn("620", cmd_portal)

    async def _run_game_session(
        self,
        data_root: Path,
        user_id: str,
        shots_to_fire: int,
    ) -> dict:
        port = find_free_port()
        env = os.environ.copy()
        env["ALLOW_PRE_SANDBOXED_FALLBACK"] = "1"
        launcher = str(PROJECT_ROOT / "engine" / "launch_phase2.py")

        proc = subprocess.Popen(
            [
                sys.executable,
                launcher,
                "--user",
                user_id,
                "--app-id",
                "0",
                "--data-root",
                str(data_root),
                "--port",
                str(port),
                "--width",
                "1280",
                "--height",
                "720",
                "--fps",
                "60",
                "--allow-pre-sandboxed",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        base_url = f"http://127.0.0.1:{port}"
        try:
            initial_status = None
            final_status = None
            async with ClientSession() as session:
                for _ in range(50):
                    try:
                        async with session.get(f"{base_url}/api/session/status", timeout=1.0) as resp:
                            if resp.status == 200:
                                st = await resp.json()
                                if st.get("game_running") and st.get("savegame") is not None:
                                    initial_status = st
                                    break
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)

                self.assertIsNotNone(initial_status, f"Session for {user_id} failed to start")

                async with session.ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
                    # Wait for initial SDP offer
                    for _ in range(30):
                        msg = await ws.receive(timeout=5.0)
                        self.assertEqual(msg.type, WSMsgType.TEXT)
                        payload = json.loads(msg.data)
                        if payload.get("type") == "offer":
                            break

                    # Fire the laser `shots_to_fire` times (each shot in CyberArena 3D awards +250 points and saves immediately)
                    for _ in range(shots_to_fire):
                        await ws.send_json({"type": "keydown", "code": "KeyF", "key": "f"})
                        await asyncio.sleep(0.08)
                        await ws.send_json({"type": "keyup", "code": "KeyF", "key": "f"})
                        await asyncio.sleep(0.12)

                    async with session.get(f"{base_url}/api/session/status", timeout=1.0) as resp:
                        final_status = await resp.json()

                    # Press Escape to cleanly quit the game and terminate the ephemeral container
                    await ws.send_json({"type": "keydown", "code": "Escape", "key": "Escape"})
                    await asyncio.sleep(0.1)
                    await ws.send_json({"type": "keyup", "code": "Escape", "key": "Escape"})
                    await asyncio.sleep(0.5)

            exit_code = proc.wait(timeout=8)
            self.assertEqual(exit_code, 0)
            return {"initial": initial_status, "final": final_status}
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            if proc.stdout:
                proc.stdout.close()

    async def test_03_multi_user_persistent_saves_and_isolation_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud_gaming_p2_e2e_") as tmpdir:
            data_root = Path(tmpdir)

            # 1. Run Session 1 for "alice": starts fresh (high_score=0, sessions_played=1), fires 1 laser shot (+250 pts)
            alice_run1 = await self._run_game_session(data_root, user_id="alice", shots_to_fire=1)
            self.assertEqual(alice_run1["initial"]["user_id"], "alice")
            self.assertEqual(alice_run1["initial"]["savegame"]["high_score"], 0)
            self.assertEqual(alice_run1["initial"]["savegame"]["sessions_played"], 1)
            self.assertEqual(alice_run1["final"]["savegame"]["high_score"], 250)
            self.assertEqual(alice_run1["final"]["savegame"]["last_score"], 250)

            # Verify savegame.json exists on disk in alice's persistent storage
            alice_save = data_root / "users" / "alice" / "home" / ".local" / "share" / "cyberarena" / "savegame.json"
            self.assertTrue(alice_save.exists(), "Alice's savegame.json must persist after container destruction")

            # 2. Run Session 2 for "alice": new ephemeral container, must load high_score=250 & sessions_played=2 at startup!
            alice_run2 = await self._run_game_session(data_root, user_id="alice", shots_to_fire=2)
            self.assertEqual(alice_run2["initial"]["savegame"]["high_score"], 250)
            self.assertEqual(alice_run2["initial"]["savegame"]["sessions_played"], 2)
            self.assertEqual(alice_run2["final"]["savegame"]["high_score"], 500)

            # 3. Run Session 3 for "bob": must be strictly isolated from alice (starts at high_score=0, sessions_played=1)
            bob_run1 = await self._run_game_session(data_root, user_id="bob", shots_to_fire=0)
            self.assertEqual(bob_run1["initial"]["user_id"], "bob")
            self.assertEqual(bob_run1["initial"]["savegame"]["high_score"], 0)
            self.assertEqual(bob_run1["initial"]["savegame"]["sessions_played"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


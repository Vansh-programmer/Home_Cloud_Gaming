#!/usr/bin/env bash
"""":
exec python3 "$0" "$@"
"""
# ==============================================================================
# RYOKU CLOUD GAMING // SUNSHINE SANDBOXED GAME LAUNCHER
# ==============================================================================
# Ensures that when Moonlight connects via Sunshine, the player is strictly
# confined inside Ryoku's Bubblewrap (bwrap) ephemeral container.
#
# SECURITY ENFORCEMENT:
# 1. Host desktop and /home/vansh are 100% BLOCKED.
# 2. Host files, browsers, and terminal cannot be accessed.
# 3. Only the specific game window runs inside an isolated virtual display.
# 4. As soon as the game exits, the container and Moonlight stream terminate.
# ==============================================================================

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.sandbox import EphemeralSandbox, SandboxConfig
from engine.steam_manager import SteamLibraryManager
from engine.storage_manager import UserStorageManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Ryoku Sandboxed Sunshine Runner")
    parser.add_argument("--app-id", default="0", help="Game App ID to launch")
    parser.add_argument("--user", default="player", help="User profile for save storage")
    parser.add_argument("--width", type=int, default=1920, help="Stream width")
    parser.add_argument("--height", type=int, default=1080, help="Stream height")
    parser.add_argument("--fps", type=int, default=120, help="Stream FPS (defaults to 120 for Moonlight)")
    parser.add_argument("--launch-options", default=None, help="Custom game launch options")
    args = parser.parse_args()

    session_id = f"sunshine-{args.user}-{int(time.time())}"
    print(f"[RYOKU SUNSHINE] Initializing isolated session: {session_id} for app {args.app_id}")

    storage_mgr = UserStorageManager(PROJECT_ROOT / "data" / "users")
    user_dirs = storage_mgr.ensure_user_storage(args.user)

    steam_mgr = SteamLibraryManager(PROJECT_ROOT / "data" / "shared_steam_library")
    shared_steam_dir = steam_mgr.base_dir if steam_mgr.base_dir.exists() else None

    # Check for game directory (Steam, Epic/Heroic, or built-in test game)
    game_dir = None
    if args.app_id != "0":
        installed = steam_mgr.get_installed_game(args.app_id)
        if installed and installed.install_dir.exists():
            game_dir = installed.install_dir

    sandbox_cfg = SandboxConfig(
        session_id=session_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
        user_id=args.user,
        app_id=args.app_id,
        game_dir=game_dir,
        shared_steam_dir=shared_steam_dir,
        user_persist_dir=user_dirs["persist_dir"],
        user_steam_dot_dir=user_dirs["steam_dot_dir"],
        user_steam_dir=user_dirs["steam_dir"],
        user_local_share_dir=user_dirs["local_share_dir"],
        user_config_dir=user_dirs["config_dir"],
    )

    sandbox = EphemeralSandbox(sandbox_cfg)
    sandbox.prepare_directories()

    # Determine command to launch inside the isolated container
    if args.app_id == "0":
        # Built-in CyberArena 3D
        inner_cmd = ["/game_bin/arena3d"]
    elif args.app_id == "7":
        # Steam Big Picture in GamepadUI mode
        inner_cmd = ["steam", "-gamepadui", "-silent", "-nochatui"]
    elif args.app_id.startswith("heroic-"):
        # Heroic / Epic Games direct launch
        heroic_app_name = args.app_id[len("heroic-"):]
        inner_cmd = ["heroic", "--no-gui", "--launch", heroic_app_name]
    else:
        # Steam game direct launch inside the container
        inner_cmd = ["steam", f"steam://rungameid/{args.app_id}"]

    if args.launch_options:
        inner_cmd.extend(args.launch_options.split())

    # Build bubblewrap command ensuring strict isolation
    bwrap_cmd = sandbox.build_bwrap_command(inner_cmd)

    print(f"[RYOKU SUNSHINE] Launching isolated game container (Host desktop is 100% blocked)...")
    proc = subprocess.Popen(bwrap_cmd)

    def handle_exit(sig, frame):
        print(f"[RYOKU SUNSHINE] Received signal {sig}, terminating container...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        sandbox.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        retcode = proc.wait()
        print(f"[RYOKU SUNSHINE] Game process exited with code {retcode}. Cleaning up sandbox.")
    finally:
        sandbox.cleanup()


if __name__ == "__main__":
    main()

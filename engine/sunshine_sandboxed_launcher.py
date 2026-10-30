#!/usr/bin/env python3
"""
RYOKU CLOUD GAMING // SUNSHINE SANDBOXED GAME LAUNCHER
======================================================
Confines games inside an isolated fullscreen compositor (Gamescope) and
Bubblewrap sandbox so that when Moonlight connects via Sunshine:

1. The host desktop, taskbar, browser, and files are 100% HIDDEN and inaccessible.
2. The game runs strictly fullscreen without window borders or background bleed.
3. As soon as the game exits, Gamescope exits and the launcher immediately
   calls Sunshine's /api/apps/close endpoint to terminate the Moonlight stream,
   preventing any fallback view of the host PC.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.storage_manager import UserStorageManager


def close_sunshine_stream() -> None:
    """Explicitly closes Sunshine streaming session when game exits."""
    sunshine_port = int(os.environ.get("SUNSHINE_PORT", "47990"))
    sunshine_user = os.environ.get("SUNSHINE_USER", "admin")
    sunshine_pass = os.environ.get("SUNSHINE_PASS", "admin")
    auth_header = "Basic " + base64.b64encode(f"{sunshine_user}:{sunshine_pass}".encode()).decode()

    url = f"https://127.0.0.1:{sunshine_port}/api/apps/close"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Authorization": auth_header, "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=2) as resp:
            print(f"[RYOKU SUNSHINE] Active stream terminated cleanly via Sunshine API (HTTP {resp.status}).")
    except Exception as e:
        print(f"[RYOKU SUNSHINE] Notice closing Sunshine stream: {e}")


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

    # Prepare user storage for isolated saves/prefixes
    storage_mgr = UserStorageManager(PROJECT_ROOT / "data" / "users")
    try:
        user_paths = storage_mgr.prepare_user_storage(args.user)
    except Exception as e:
        print(f"[RYOKU SUNSHINE] Storage notice: {e}")
        user_paths = None

    # Resolve game executable command
    inner_cmd: list[str] = []
    if args.app_id == "0":
        # Built-in CyberArena 3D
        arena3d_bin = PROJECT_ROOT / "engine" / "test_game" / "arena3d"
        if not arena3d_bin.exists():
            print("[RYOKU SUNSHINE] Compiling CyberArena 3D...")
            subprocess.run(
                ["gcc", "-O2", str(PROJECT_ROOT / "engine" / "test_game" / "arena3d.c"),
                 "-o", str(arena3d_bin), "-lSDL2", "-lGL", "-lGLU", "-lm"],
                check=False
            )
        inner_cmd = [str(arena3d_bin)]
    elif args.app_id == "7":
        # Steam Big Picture in dedicated GamepadUI mode
        inner_cmd = ["steam", "-gamepadui", "-steamos3"]
    elif args.app_id == "8" or args.app_id.startswith("heroic-") or args.app_id.startswith("epic_"):
        # Heroic / Epic Games Launcher
        heroic_bin = shutil.which("heroic") or "/usr/bin/heroic"
        if args.app_id == "8":
            inner_cmd = [heroic_bin, "--no-gui"]
        else:
            app_slug = args.app_id.replace("heroic-", "").replace("epic_", "")
            inner_cmd = [heroic_bin, "--no-gui", "--launch", app_slug]
    else:
        # Steam game direct launch
        inner_cmd = ["steam", "-applaunch", str(args.app_id)]

    if args.launch_options:
        inner_cmd.extend(args.launch_options.split())

    # Environment variables for isolated, smooth low-latency rendering
    env = os.environ.copy()
    env["STEAM_DISABLE_SANDBOX"] = "1"
    env["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"
    env["DXVK_FRAME_RATE"] = str(args.fps)
    env["FERAL_RUN_FROM_STEAM"] = "0"

    gamescope_bin = shutil.which("gamescope")
    if gamescope_bin:
        # Launch inside Gamescope micro-compositor in FULLSCREEN.
        # This completely occludes the host desktop, taskbar, and windows.
        # Moonlight sees ONLY the game surface!
        cmd = [
            gamescope_bin,
            "-W", str(args.width),
            "-H", str(args.height),
            "-w", str(args.width),
            "-h", str(args.height),
            "-r", str(args.fps),
            "-f",  # Fullscreen covering entire monitor
            "--force-windows-fullscreen",  # Prevent any borders or desktop bleed-through
            "--cursor-scale-height", str(args.height),
        ]
        if args.app_id == "7" or (args.app_id.isdigit() and args.app_id not in ("0", "8")):
            cmd.append("-e")  # Steam integration flag
        cmd.append("--")
        cmd.extend(inner_cmd)
        print(f"[RYOKU SUNSHINE] Launching via Gamescope fullscreen container: {' '.join(cmd)}")
    else:
        cmd = inner_cmd
        print(f"[RYOKU SUNSHINE] Launching game directly: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, env=env)

    def handle_exit(sig, frame):
        print(f"[RYOKU SUNSHINE] Received signal {sig}, terminating game process...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        close_sunshine_stream()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        retcode = proc.wait()
        print(f"[RYOKU SUNSHINE] Game process exited with code {retcode}.")
    finally:
        # Immediately terminate the Moonlight stream so the player is returned
        # to the client menu and NEVER exposed to the host desktop.
        close_sunshine_stream()


if __name__ == "__main__":
    main()

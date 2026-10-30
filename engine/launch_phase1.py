#!/usr/bin/env python3
"""
Isolated Session Launcher (Phases 1 & 2):
Starts an isolated, ephemeral Bubblewrap (bwrap) container running the headless
Weston + Xwayland + PipeWire + GStreamer NVENC WebRTC server and target game
with per-user persistent storage and a shared read-only Steam library.

Guarantees that all temporary session files and processes are destroyed on exit,
while preserving only the active user's persistent saves and Steam login tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.sandbox import EphemeralSandbox, SandboxConfig  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.storage_manager import UserStorageManager, validate_user_id  # noqa: E402
from engine.webrtc_streamer import QUALITY_PRESETS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Isolated Cloud Gaming Session")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for HTTP/WebSocket server (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP/WebSocket port (default: 8080)")
    parser.add_argument("--session-id", default="", help="Optional explicit session ID")
    parser.add_argument("--width", type=int, default=1920, help="Stream width (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Stream height (default: 1080)")
    parser.add_argument("--fps", type=int, default=60, help="Stream FPS (default: 60)")
    parser.add_argument("--quality", default="high", choices=list(QUALITY_PRESETS.keys()))
    parser.add_argument("--user", default="vansh", help="User ID for isolated persistent saves & Steam profile")
    parser.add_argument(
        "--app-id",
        default="0",
        help="Target AppID: '0' for CyberArena 3D, '7' for Steam Big Picture, or any Steam AppID",
    )
    parser.add_argument("--data-root", default="", help="Optional custom data directory root")
    parser.add_argument("--game-cmd", default="", help="Optional custom game command inside container")
    parser.add_argument("--list-games", action="store_true", help="List discovered games and exit")
    parser.add_argument("--user-status", action="store_true", help="Print user persistent storage status and exit")
    parser.add_argument("--display-num", type=int, default=0, help="Explicit display number (0 = auto-detect free display)")
    parser.add_argument("--launch-options", default="", help="Steam launch options (e.g. WINEDLLOVERRIDES=... %%command%%)")
    parser.add_argument(
        "--allow-pre-sandboxed",
        action="store_true",
        help="Allow running inside an already-sandboxed test runner where nested bwrap is blocked",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve() if args.data_root else None
    storage_mgr = UserStorageManager(data_root=data_root)
    storage_mgr.ensure_base_directories()
    steam_mgr = SteamLibraryManager(storage_mgr.shared_steam_dir)

    if args.list_games:
        games = [g.to_dict() for g in steam_mgr.list_games()]
        print(json.dumps(games, indent=2))
        return 0

    user_id = validate_user_id(args.user)
    if args.user_status:
        print(json.dumps(storage_mgr.get_user_steam_status(user_id), indent=2))
        return 0

    user_paths = storage_mgr.prepare_user_storage(user_id)

    extra_binds = {}
    try:
        from engine.host_library import collect_host_mounts, host_library_enabled
        if host_library_enabled():
            for m in collect_host_mounts(storage_mgr.data_root):
                extra_binds[str(m.src)] = m.dst
    except Exception:
        pass

    session_id = args.session_id.strip() if args.session_id.strip() else f"cg-{user_id}-{uuid.uuid4().hex[:6]}"
    cfg = SandboxConfig(
        session_id=session_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
        user_id=user_id,
        app_id=str(args.app_id),
        shared_steam_dir=storage_mgr.shared_steam_dir,
        user_steam_dot_dir=user_paths.steam_dot_dir,
        user_local_share_dir=user_paths.local_share_dir,
        user_config_dir=user_paths.config_dir,
        extra_ro_binds=extra_binds,
    )
    sandbox = EphemeralSandbox(cfg)
    sandbox.prepare_directories()

    inner_cmd = [
        "/usr/bin/python3",
        "/opt/cloudgaming/engine/session_runner.py",
        "--session-id",
        session_id,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--fps",
        str(args.fps),
        "--quality",
        args.quality,
        "--user-id",
        user_id,
        "--app-id",
        str(args.app_id),
    ]
    if args.display_num > 0:
        inner_cmd.extend(["--display-num", str(args.display_num)])
    if args.launch_options and args.launch_options.strip().lower() not in ("none", "null", ""):
        inner_cmd.extend(["--launch-options", args.launch_options.strip()])
    if args.game_cmd:
        inner_cmd.extend(["--game-cmd", args.game_cmd])

    if sandbox.can_use_bwrap():
        cmd = sandbox.build_bwrap_command(inner_cmd)
        print(
            f"[Cloud Gaming Launcher] Starting strict bwrap container for user '{user_id}', "
            f"app '{args.app_id}' (session '{session_id}')..."
        )
    else:
        print(
            f"[Cloud Gaming Launcher] Unprivileged bwrap namespaces unavailable; running isolated runtime dir "
            f"for user '{user_id}' (session '{session_id}')..."
        )
        runner_script = str(PROJECT_ROOT / "engine" / "session_runner.py")
        cmd = [
            "env",
            "-i",
            f"PATH={os.environ.get('PATH', '/usr/bin:/bin')}",
            f"HOME={user_paths.user_root / 'home'}",
            f"XDG_RUNTIME_DIR={sandbox.runtime_dir}",
            f"XDG_DATA_HOME={user_paths.local_share_dir}",
            f"XDG_CONFIG_HOME={user_paths.config_dir}",
            "XDG_CURRENT_DESKTOP=gamescope",
            f"TMPDIR={sandbox.tmp_dir}",
            f"SESSION_STATE_DIR={sandbox.runtime_dir}",
            f"CLOUD_USER_ID={user_id}",
            f"CLOUD_APP_ID={args.app_id}",
            "SANDBOX_MODE=pre-sandboxed-env",
            f"STUN_SERVER={os.environ.get('STUN_SERVER', '')}",
            f"TURN_SERVER={os.environ.get('TURN_SERVER', '')}",
            f"TURN_SERVERS={os.environ.get('TURN_SERVERS', '')}",
            f"RTP_MIN_PORT={os.environ.get('RTP_MIN_PORT', '30000')}",
            f"RTP_MAX_PORT={os.environ.get('RTP_MAX_PORT', '60000')}",
            sys.executable,
            runner_script,
            "--session-id",
            session_id,
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--width",
            str(args.width),
            "--height",
            str(args.height),
            "--fps",
            str(args.fps),
            "--quality",
            args.quality,
            "--user-id",
            user_id,
            "--app-id",
            str(args.app_id),
        ]
        if args.display_num > 0:
            cmd.extend(["--display-num", str(args.display_num)])
        if args.launch_options and args.launch_options.strip().lower() not in ("none", "null", ""):
            cmd.extend(["--launch-options", args.launch_options.strip()])
        if args.game_cmd:
            cmd.extend(["--game-cmd", args.game_cmd])

    proc = None
    try:
        proc = subprocess.Popen(cmd)

        def _forward_signal(signum: int, _frame: object) -> None:
            if proc and proc.poll() is None:
                proc.terminate()

        signal.signal(signal.SIGINT, _forward_signal)
        signal.signal(signal.SIGTERM, _forward_signal)

        return proc.wait()
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        sandbox.cleanup()
        print(
            f"[Cloud Gaming Launcher] Ephemeral session '{session_id}' wiped; "
            f"persistent saves for user '{user_id}' preserved."
        )


if __name__ == "__main__":
    sys.exit(main())

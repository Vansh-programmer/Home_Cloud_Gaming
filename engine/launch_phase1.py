#!/usr/bin/env python3
"""
Phase 1 Launcher: Starts an isolated, ephemeral Bubblewrap (bwrap) container
running the headless Weston + Xwayland + PipeWire + GStreamer NVENC WebRTC server
and the CyberArena 3D OpenGL test game.

Guarantees that all temporary session files and processes are destroyed on exit.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Phase 1 Isolated Cloud Gaming Prototype")
    parser.add_argument("--port", type=int, default=8080, help="HTTP/WebSocket port (default: 8080)")
    parser.add_argument("--width", type=int, default=1280, help="Stream width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Stream height (default: 720)")
    parser.add_argument("--fps", type=int, default=60, help="Stream FPS (default: 60)")
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high", "ultra"])
    parser.add_argument("--game-cmd", default="", help="Optional custom game command inside container")
    parser.add_argument(
        "--allow-pre-sandboxed",
        action="store_true",
        help="Allow running inside an already-sandboxed test runner where nested bwrap is blocked",
    )
    args = parser.parse_args()

    session_id = f"p1-{uuid.uuid4().hex[:8]}"
    cfg = SandboxConfig(
        session_id=session_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    sandbox = EphemeralSandbox(cfg)
    sandbox.prepare_directories()

    inner_cmd = [
        "/usr/bin/python3",
        "/opt/cloudgaming/engine/session_runner.py",
        "--session-id",
        session_id,
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
    ]
    if args.game_cmd:
        inner_cmd.extend(["--game-cmd", args.game_cmd])

    if sandbox.can_use_bwrap():
        cmd = sandbox.build_bwrap_command(inner_cmd)
        print(f"[Phase 1 Launcher] Starting strict bwrap container for session '{session_id}'...")
    elif args.allow_pre_sandboxed or os.environ.get("ALLOW_PRE_SANDBOXED_FALLBACK") == "1":
        print(
            f"[Phase 1 Launcher] Pre-sandboxed environment detected; running isolated runtime dir for '{session_id}'..."
        )
        runner_script = str(PROJECT_ROOT / "engine" / "session_runner.py")
        cmd = [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            f"HOME={sandbox.home_dir}",
            f"XDG_RUNTIME_DIR={sandbox.runtime_dir}",
            f"TMPDIR={sandbox.tmp_dir}",
            f"SESSION_STATE_DIR={sandbox.runtime_dir}",
            "SANDBOX_MODE=pre-sandboxed-env",
            sys.executable,
            runner_script,
            "--session-id",
            session_id,
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
        ]
        if args.game_cmd:
            cmd.extend(["--game-cmd", args.game_cmd])
    else:
        sandbox.cleanup()
        print(
            "ERROR: Bubblewrap (bwrap) namespace creation failed. Refusing to run without container isolation.",
            file=sys.stderr,
        )
        return 1

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
        print(f"[Phase 1 Launcher] Ephemeral session '{session_id}' directory deleted.")


if __name__ == "__main__":
    sys.exit(main())


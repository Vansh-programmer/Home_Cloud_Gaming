"""
Phase 1 Automated Verification Suite:
1. Sandbox command construction, security invariants, and ephemeral directory destruction.
2. End-to-end headless Weston + Xwayland + PipeWire + CyberArena 3D + GStreamer NVENC WebRTC session:
   - HTTP status endpoint & HTML player serving
   - WebRTC signaling (SDP Offer with H264 video, Opus audio, and RTCDataChannel)
   - Dynamic NVENC quality switching (Low/Medium/High/Ultra)
   - Input injection (Keyboard, Mouse, Gamepad) & Ping/Pong RTT telemetry
   - Automatic session termination when the game exits (pressing Escape in-game)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

from aiohttp import ClientSession, WSMsgType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.sandbox import EphemeralSandbox, SandboxConfig  # noqa: E402


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPhase1IsolatedStreaming(unittest.IsolatedAsyncioTestCase):
    def test_01_sandbox_security_invariants_and_cleanup(self) -> None:
        cfg = SandboxConfig(session_id="unit-test-sec", width=1280, height=720, fps=60)
        sb = EphemeralSandbox(cfg)
        sb.prepare_directories()
        try:
            self.assertTrue(sb.session_root.exists())
            cmd = sb.build_bwrap_command(["/usr/bin/id"])
            cmd_str = " ".join(cmd)

            # Verify namespace isolation flags
            self.assertIn("--unshare-user", cmd)
            self.assertIn("--unshare-pid", cmd)
            self.assertIn("--unshare-ipc", cmd)
            self.assertIn("--unshare-uts", cmd)
            self.assertIn("--clearenv", cmd)
            self.assertIn("--die-with-parent", cmd)

            # Verify host user home is wiped by --tmpfs /home and never mounted at /home/vansh
            self.assertIn("--tmpfs /home --dir /home/gamer", cmd_str)
            self.assertNotIn(" /home/vansh ", cmd_str)
            self.assertNotIn("/dev/input", cmd_str)
            self.assertNotIn("/dev/snd", cmd_str)

            # Verify GPU device nodes are bound
            self.assertIn("/dev/dri", cmd_str)
        finally:
            sb.cleanup()
            self.assertFalse(sb.session_root.exists(), "Ephemeral session directory must be deleted")

    async def test_02_end_to_end_isolated_webrtc_session_and_game_exit(self) -> None:
        port = find_free_port()
        env = os.environ.copy()
        env["ALLOW_PRE_SANDBOXED_FALLBACK"] = "1"

        launcher = str(PROJECT_ROOT / "engine" / "launch_phase1.py")
        proc = subprocess.Popen(
            [
                sys.executable,
                launcher,
                "--port",
                str(port),
                "--width",
                "1280",
                "--height",
                "720",
                "--fps",
                "60",
                "--quality",
                "high",
                "--allow-pre-sandboxed",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Wait for HTTP server to come up
            status_data = None
            async with ClientSession() as session:
                for _ in range(50):
                    try:
                        async with session.get(f"{base_url}/api/session/status", timeout=1.0) as resp:
                            if resp.status == 200:
                                status_data = await resp.json()
                                if status_data.get("game_running"):
                                    break
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)

                self.assertIsNotNone(status_data, "Session server failed to start")
                self.assertEqual(status_data["state"], "ready")
                self.assertTrue(status_data["game_running"])
                self.assertEqual(status_data["width"], 1280)
                self.assertEqual(status_data["height"], 720)

                # Verify prototype HTML is served
                async with session.get(f"{base_url}/") as html_resp:
                    self.assertEqual(html_resp.status, 200)
                    html_text = await html_resp.text()
                    self.assertIn("Ryoku Cloud", html_text)

                # Connect WebSocket signaling client & verify SDP Offer + Input + Quality switch
                async with session.ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
                    got_status = False
                    got_offer = False
                    offer_sdp = ""

                    for _ in range(30):
                        msg = await ws.receive(timeout=5.0)
                        self.assertEqual(msg.type, WSMsgType.TEXT, f"Unexpected WS message: {msg}")
                        payload = json.loads(msg.data)
                        if payload.get("type") == "error":
                            self.fail(f"Server reported WebRTC pipeline error: {payload.get('error')}")
                        if payload.get("type") == "status":
                            got_status = True
                        elif payload.get("type") == "offer":
                            got_offer = True
                            offer_sdp = payload.get("sdp", "")
                            break

                    self.assertTrue(got_status, "Did not receive initial status over WebSocket")
                    self.assertTrue(got_offer, "Did not receive WebRTC SDP Offer from GStreamer webrtcbin")
                    self.assertIn("m=video", offer_sdp)
                    self.assertIn("H264", offer_sdp)
                    self.assertIn("m=audio", offer_sdp)
                    self.assertIn("OPUS", offer_sdp)
                    self.assertIn("m=application", offer_sdp)

                    # Test Ping/Pong RTT measurement
                    await ws.send_json({"type": "ping", "client_ts": 12345.0})
                    # Test Dynamic Quality Change
                    await ws.send_json({"type": "quality", "quality": "medium"})

                    got_pong = False
                    got_quality_ack = False
                    for _ in range(15):
                        msg = await ws.receive(timeout=3.0)
                        if msg.type == WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("type") == "pong" and data.get("client_ts") == 12345.0:
                                got_pong = True
                            elif data.get("type") == "quality_ack" and data.get("quality") == "medium":
                                self.assertEqual(data.get("bitrate_kbps"), 8000)
                                got_quality_ack = True
                            if got_pong and got_quality_ack:
                                break

                    self.assertTrue(got_pong, "Did not receive pong response")
                    self.assertTrue(got_quality_ack, "Did not receive quality_ack response")

                    # Inject Keyboard, Mouse, and Gamepad inputs
                    await ws.send_json({"type": "keydown", "code": "KeyF", "key": "f"})
                    await asyncio.sleep(0.05)
                    await ws.send_json({"type": "keyup", "code": "KeyF", "key": "f"})
                    await ws.send_json({"type": "mousemove", "dx": 25, "dy": -10})
                    await ws.send_json({"type": "gamepad", "axes": [0.0, -0.8, 0.4, 0.0], "buttons": [True]})
                    await asyncio.sleep(0.1)

                    # Now send Escape key to the game to verify quitting the game self-terminates the session!
                    await ws.send_json({"type": "keydown", "code": "Escape", "key": "Escape"})
                    await asyncio.sleep(0.1)
                    await ws.send_json({"type": "keyup", "code": "Escape", "key": "Escape"})
                    await asyncio.sleep(0.6)

            # Wait for the session launcher to automatically exit and clean up its ephemeral directory
            exit_code = proc.wait(timeout=8)
            self.assertEqual(exit_code, 0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()


if __name__ == "__main__":
    unittest.main(verbosity=2)

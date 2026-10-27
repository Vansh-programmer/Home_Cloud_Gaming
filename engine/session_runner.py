"""
Isolated Session Runner Daemon.

Runs inside the ephemeral sandbox container:
1. Verifies strict isolation from host home, host X11/Wayland, physical inputs, and host soundcard.
2. Starts isolated PipeWire + WirePlumber + PipeWire-Pulse with a virtual null-sink (cloud_sink).
3. Starts headless Weston kiosk compositor + isolated Xwayland display server.
4. Connects IsolatedInputManager (libX11 + libXtst) for fullscreen window enforcement & input injection.
5. Launches ONLY the target game process and monitors its lifecycle.
6. Runs the GStreamer NVENC + Opus WebRTC signaling & streaming server.
7. Tears down and exits immediately when the game process ends.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from aiohttp import WSMsgType, web
from gi.repository import GLib

# Ensure project root is on sys.path both on host and inside /opt/cloudgaming
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.input_manager import IsolatedInputManager  # noqa: E402
from engine.sandbox import run_isolation_self_check  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.webrtc_streamer import QUALITY_PRESETS, WebRTCPeerStream  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("session_runner")


class IsolatedSessionRuntime:
    """Manages the display, audio, game process, input manager, and WebRTC peers inside one session."""

    def __init__(
        self,
        session_id: str,
        width: int = 1280,
        height: int = 720,
        fps: int = 60,
        quality: str = "high",
        game_cmd: Optional[List[str]] = None,
        port: int = 8080,
        user_id: str = "default",
        app_id: str = "0",
        display_num: int = 0,
        launch_options: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality if quality in QUALITY_PRESETS else "high"
        self.port = port
        self.user_id = user_id or os.environ.get("CLOUD_USER_ID", "default")
        self.app_id = str(app_id or os.environ.get("CLOUD_APP_ID", "0"))
        self.launch_options = launch_options or os.environ.get("CLOUD_LAUNCH_OPTIONS", "")
        os.environ["CLOUD_USER_ID"] = self.user_id
        os.environ["CLOUD_APP_ID"] = self.app_id

        if game_cmd:
            self.game_cmd = game_cmd
        else:
            shared_dir = Path("/steam_shared") if Path("/steam_shared").exists() else (PROJECT_ROOT / "data" / "shared_steam_library")
            inside_container = Path("/opt/cloudgaming").exists()
            steam_mgr = SteamLibraryManager(shared_dir)
            self.game_cmd = steam_mgr.build_launch_command(self.app_id, inside_container=inside_container)

        self.state = "starting"
        self.error_message: Optional[str] = None
        self.started_at = time.time()
        self.last_input_at = time.time()
        self.isolation_report = run_isolation_self_check()

        raw_xdg = os.environ.get("XDG_RUNTIME_DIR", f"/tmp/cg-xdg-{session_id}")
        self.xdg_dir = Path(raw_xdg)
        try:
            self.xdg_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.xdg_dir, 0o700)
        except OSError:
            self.xdg_dir = Path(f"/tmp/cg-xdg-{session_id}")
            self.xdg_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.xdg_dir, 0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(self.xdg_dir)

        # Dynamic display and audio sink allocation for multi-instance support
        self.use_unix_display = self._can_use_unix_x11_socket()
        self.display_num = self._resolve_display_num(int(display_num or 0))
        self.display_name = f":{self.display_num}" if self.use_unix_display else f"127.0.0.1:{self.display_num}"
        self.sink_name = f"cloud_sink_{self.display_num}"
        self.pulse_source = f"{self.sink_name}.monitor"
        self.audio_available = False

        self._procs: List[subprocess.Popen] = []
        self.game_proc: Optional[subprocess.Popen] = None
        self.input_manager: Optional[IsolatedInputManager] = None
        self.active_peer: Optional[WebRTCPeerStream] = None
        self.active_ws: Optional[web.WebSocketResponse] = None
        self._glib_loop: Optional[GLib.MainLoop] = None
        self._glib_thread: Optional[threading.Thread] = None
        self._shutdown_event = asyncio.Event()

    def _start_glib_loop(self) -> None:
        self._glib_loop = GLib.MainLoop()
        self._glib_thread = threading.Thread(target=self._glib_loop.run, daemon=True)
        self._glib_thread.start()

    def _resolve_display_num(self, requested: int = 0) -> int:
        """Resolve a non-conflicting display number for isolated Xwayland."""
        if requested > 0:
            return requested
        if self.use_unix_display:
            for disp in range(99, 160):
                sock = Path(f"/tmp/.X11-unix/X{disp}")
                lock = Path(f"/tmp/.X{disp}-lock")
                if not sock.exists() and not lock.exists():
                    return disp
            return 99
        else:
            start_disp = 90 + (self.port % 50)
            for offset in range(60):
                cand = 90 + ((start_disp - 90 + offset) % 60)
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.bind(("0.0.0.0", 6000 + cand))
                    return cand
                except OSError:
                    continue
            return start_disp

    def _can_use_unix_x11_socket(self) -> bool:
        if os.getuid() != 0:
            return False
        x11_dir = Path("/tmp/.X11-unix")
        try:
            x11_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(x11_dir, 0o1777)
            return os.access(x11_dir, os.W_OK) and x11_dir.stat().st_uid == 0
        except Exception:
            return False

    def start_isolated_audio(self) -> None:
        """Start isolated D-Bus, PipeWire, WirePlumber, and PipeWire-Pulse with a virtual null-sink."""
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(self.xdg_dir)
        try:
            dbus_sock = self.xdg_dir / "bus"
            dbus_proc = subprocess.Popen(
                [
                    "dbus-daemon",
                    "--session",
                    f"--address=unix:path={dbus_sock}",
                    "--nofork",
                    "--nopidfile",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(dbus_proc)
            dbus_addr = f"unix:path={dbus_sock}"
            env["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
            time.sleep(0.2)

            pw_proc = subprocess.Popen(
                ["pipewire"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(pw_proc)
            time.sleep(0.35)

            wp_proc = subprocess.Popen(
                ["wireplumber"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(wp_proc)

            pulse_dir = self.xdg_dir / "pulse"
            env["PULSE_RUNTIME_PATH"] = str(pulse_dir)
            os.environ["PULSE_RUNTIME_PATH"] = str(pulse_dir)

            pwp_proc = subprocess.Popen(
                ["pipewire-pulse"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(pwp_proc)
            pulse_sock = pulse_dir / "native"
            for _ in range(25):
                if pulse_sock.exists():
                    break
                time.sleep(0.05)

            pulse_server = f"unix:{pulse_sock}"
            env["PULSE_SERVER"] = pulse_server
            os.environ["PULSE_SERVER"] = pulse_server

            res = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={self.sink_name}",
                    "sink_properties=device.description=CloudGamingIsolatedAudio",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )
            if res.returncode == 0:
                subprocess.run(
                    ["pactl", "set-default-sink", self.sink_name],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                os.environ["PULSE_SINK"] = self.sink_name
                os.environ["PULSE_SOURCE"] = self.pulse_source
                self.audio_available = True
                logger.info("Isolated PipeWire-Pulse virtual sink '%s' initialized", self.sink_name)
            else:
                logger.warning("pactl load-module returned %d; using silent fallback", res.returncode)
        except Exception as exc:
            logger.warning("Isolated audio initialization warning: %s", exc)

    def start_isolated_display(self) -> None:
        """Start headless Weston kiosk compositor and rootful Xwayland server."""
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(self.xdg_dir)
        wayland_socket = f"wayland-cloud-{self.display_num}"

        weston_cmd = [
            "weston",
            "--backend=headless",
            "--renderer=gl",
            "--shell=kiosk",
            "--no-config",
            f"--socket={wayland_socket}",
            f"--width={self.width}",
            f"--height={self.height}",
        ]
        weston_proc = subprocess.Popen(
            weston_cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(weston_proc)

        # Wait for Wayland socket to appear
        wl_path = self.xdg_dir / wayland_socket
        for _ in range(30):
            if wl_path.exists():
                break
            time.sleep(0.1)

        env["WAYLAND_DISPLAY"] = wayland_socket
        os.environ["WAYLAND_DISPLAY"] = wayland_socket

        if self.use_unix_display:
            xw_cmd = [
                "Xwayland",
                f":{self.display_num}",
                "-ac",
                "-noreset",
                "-nolisten",
                "tcp",
                "-geometry",
                f"{self.width}x{self.height}",
            ]
        else:
            xw_cmd = [
                "Xwayland",
                f":{self.display_num}",
                "-ac",
                "-noreset",
                "-nolisten",
                "unix",
                "-listen",
                "tcp",
                "-geometry",
                f"{self.width}x{self.height}",
            ]

        xw_proc = subprocess.Popen(
            xw_cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(xw_proc)
        os.environ["DISPLAY"] = self.display_name

        self.input_manager = IsolatedInputManager(self.display_name, self.width, self.height)
        if not self.input_manager.connect(retries=40, delay=0.1):
            raise RuntimeError(f"Failed to connect IsolatedInputManager to Xwayland ({self.display_name})")
        logger.info("Isolated Xwayland display ready on %s (%dx%d)", self.display_name, self.width, self.height)

    def start_game(self) -> None:
        """Launch the single target game process inside the isolated display and audio environment."""
        env = os.environ.copy()
        env["DISPLAY"] = self.display_name
        env["WAYLAND_DISPLAY"] = ""  # Force X11/Xwayland so ximagesrc & XTest work uniformly
        env["SDL_VIDEODRIVER"] = "x11"
        env["STREAM_WIDTH"] = str(self.width)
        env["STREAM_HEIGHT"] = str(self.height)
        env["PRESSURE_VESSEL_FILESYSTEMS_RO"] = "/steam_shared:/game"
        env["STEAM_COMPAT_MOUNTS"] = "/steam_shared:/game"
        env["STEAM_COMPAT_LIBRARY_PATHS"] = "/home/gamer/.local/share/Steam:/steam_shared"
        # Ultra-low latency frame pacing & driver tuning (Moonlight-class responsiveness)
        env["DXVK_FRAME_RATE"] = str(self.fps)
        env["DXVK_ASYNC"] = "1"
        env["__GL_MaxFramesAllowed"] = "1"
        env["__GL_THREADED_OPTIMIZATIONS"] = "1"
        env["__GL_SYNC_TO_VBLANK"] = "0"
        env["PROTON_ENABLE_NVAPI"] = "1"
        env["vblank_mode"] = "0"
        if self.audio_available:
            env["PULSE_SINK"] = self.sink_name
            env["SDL_AUDIODRIVER"] = "pulseaudio"
        else:
            env["SDL_AUDIODRIVER"] = "dummy"

        # Apply Steam launch options, command wrappers, and DLL overrides
        from engine.steam_manager import (
            DEFAULT_ONLINEFIX_DLL_OVERRIDES,
            SteamLibraryManager,
            parse_launch_options,
        )
        launch_opts = self.launch_options
        if not launch_opts:
            shared_dir = Path("/steam_shared") if Path("/steam_shared").exists() else (PROJECT_ROOT / "data" / "shared_steam_library")
            steam_mgr = SteamLibraryManager(shared_dir)
            launch_opts = steam_mgr.get_custom_launch_options(self.app_id)

        target_cmd, env = parse_launch_options(launch_opts, self.game_cmd, env)

        # Automatic detection for OnlineFix games: if OnlineFix DLLs, Lethal Company or Phasmophobia is present, ensure DLL overrides
        if "WINEDLLOVERRIDES" not in env:
            if (
                self.app_id in ("1966720", "739630")
                or "lethal" in str(target_cmd).lower()
                or "phasmophobia" in str(target_cmd).lower()
                or "onlinefix" in str(target_cmd).lower()
            ):
                env["WINEDLLOVERRIDES"] = DEFAULT_ONLINEFIX_DLL_OVERRIDES
                logger.info("Automatically injected WINEDLLOVERRIDES for online-fix game: %s", self.app_id)

        logger.info(
            "Launching isolated game command: %s (WINEDLLOVERRIDES: %s)",
            target_cmd,
            env.get("WINEDLLOVERRIDES", "none"),
        )
        self.game_proc = subprocess.Popen(
            target_cmd,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        for _ in range(40):
            if self.input_manager and self.input_manager.has_focused_window:
                time.sleep(0.35)
                break
            if self.game_proc.poll() is not None:
                break
            time.sleep(0.1)
        self.state = "ready"

    async def monitor_game_lifecycle(self) -> None:
        """Watch the game process; terminate the session immediately when the game exits."""
        while not self._shutdown_event.is_set():
            if self.game_proc is not None:
                ret = self.game_proc.poll()
                if ret is not None:
                    logger.info("Game process exited with code %d; ending isolated session", ret)
                    self.state = "ended"
                    self._shutdown_event.set()
                    break
            await asyncio.sleep(0.3)

    def stop_all(self) -> None:
        """Cleanly stop WebRTC pipeline, input manager, game process, compositor, and audio daemons."""
        self.state = "ended"
        if self.active_peer is not None:
            self.active_peer.stop()
            self.active_peer = None

        if self.input_manager is not None:
            self.input_manager.close()
            self.input_manager = None

        if self.game_proc is not None and self.game_proc.poll() is None:
            try:
                self.game_proc.terminate()
                self.game_proc.wait(timeout=2)
            except Exception:
                try:
                    self.game_proc.kill()
                except Exception:
                    pass

        for proc in reversed(self._procs):
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._procs.clear()

        if self._glib_loop is not None and self._glib_loop.is_running():
            self._glib_loop.quit()

    def _read_session_persistence_info(self) -> Dict[str, object]:
        data_home = Path(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")))
        save_path = data_home / "cyberarena" / "savegame.json"
        save_info: Dict[str, object] = {"high_score": 0, "sessions_played": 0, "exists": False}
        if save_path.exists():
            try:
                raw = json.loads(save_path.read_text(encoding="utf-8"))
                save_info = {
                    "high_score": int(raw.get("high_score", 0)),
                    "last_score": int(raw.get("last_score", 0)),
                    "sessions_played": int(raw.get("sessions_played", 0)),
                    "exists": True,
                }
            except Exception:
                pass

        loginusers = data_home / "Steam" / "config" / "loginusers.vdf"
        steam_remembered = False
        if loginusers.exists():
            try:
                txt = loginusers.read_text(encoding="utf-8", errors="ignore")
                steam_remembered = '"AccountName"' in txt or '"MostRecent"' in txt
            except Exception:
                pass

        return {
            "savegame": save_info,
            "steam_login_remembered": steam_remembered,
        }

    def get_status_dict(self) -> Dict[str, object]:
        now = time.time()
        preset = QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["high"])
        persist = self._read_session_persistence_info()
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "app_id": self.app_id,
            "state": self.state,
            "error": self.error_message,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "quality": self.quality,
            "bitrate_kbps": preset["bitrate_kbps"],
            "audio_enabled": self.audio_available,
            "game_running": self.game_proc is not None and self.game_proc.poll() is None,
            "game_pid": self.game_proc.pid if self.game_proc else None,
            "uptime_sec": round(now - self.started_at, 1),
            "last_input_at": self.last_input_at,
            "idle_sec": round(max(0.0, now - self.last_input_at), 1),
            "client_connected": self.active_ws is not None and not self.active_ws.closed,
            "savegame": persist["savegame"],
            "steam_login_remembered": persist["steam_login_remembered"],
            "isolation": self.isolation_report,
        }


def create_web_app(runtime: IsolatedSessionRuntime) -> web.Application:
    app = web.Application()
    web_dir = PROJECT_ROOT / "web"

    async def handle_index(_request: web.Request) -> web.StreamResponse:
        return web.FileResponse(web_dir / "prototype.html")

    async def handle_status(_request: web.Request) -> web.Response:
        return web.json_response(runtime.get_status_dict())

    async def handle_quality(request: web.Request) -> web.Response:
        data = await request.json()
        quality = str(data.get("quality", "high"))
        runtime.quality = quality if quality in QUALITY_PRESETS else "high"
        if runtime.active_peer:
            info = runtime.active_peer.set_quality(runtime.quality)
        else:
            info = {"quality": runtime.quality, **QUALITY_PRESETS[runtime.quality]}
        return web.json_response({"ok": True, **info})

    async def handle_stop(_request: web.Request) -> web.Response:
        runtime.state = "ended"
        runtime._shutdown_event.set()
        return web.json_response({"ok": True, "state": "ended"})

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15.0)
        await ws.prepare(request)

        loop = asyncio.get_running_loop()

        # Close previous peer if reconnecting
        if runtime.active_peer is not None:
            runtime.active_peer.stop()
            runtime.active_peer = None
        if runtime.active_ws is not None and not runtime.active_ws.closed:
            try:
                await runtime.active_ws.send_json(
                    {
                        "type": "replaced",
                        "message": "Stream connected on another device or browser tab.",
                    }
                )
                await runtime.active_ws.close(code=4001, message=b"replaced_by_new_client")
            except Exception:
                pass

        runtime.active_ws = ws
        runtime.state = "playing"

        def send_signaling_threadsafe(msg: dict) -> None:
            if not ws.closed:
                asyncio.run_coroutine_threadsafe(ws.send_json(msg), loop)

        def on_input_from_peer(payload: dict) -> None:
            runtime.last_input_at = time.time()
            if runtime.input_manager:
                runtime.input_manager.handle_event(payload)

        # Send initial session status immediately
        await ws.send_json({"type": "status", "status": runtime.get_status_dict()})

        peer = WebRTCPeerStream(
            display_name=runtime.display_name,
            pulse_source=runtime.pulse_source,
            width=runtime.width,
            height=runtime.height,
            fps=runtime.fps,
            quality=runtime.quality,
            on_signaling_message=send_signaling_threadsafe,
            on_input_event=on_input_from_peer,
            audio_enabled=runtime.audio_available,
        )
        runtime.active_peer = peer
        try:
            peer.start()
        except Exception as exc:
            logger.exception("Failed to start WebRTC pipeline: %s", exc)
            await ws.send_json({"type": "error", "error": str(exc)})
            return ws

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    mtype = data.get("type")
                    if mtype == "answer":
                        peer.handle_sdp_answer(str(data.get("sdp", "")))
                    elif mtype == "ice":
                        cand = data.get("candidate")
                        if isinstance(cand, dict):
                            peer.handle_ice_candidate(
                                int(cand.get("sdpMLineIndex", 0)),
                                str(cand.get("candidate", "")),
                            )
                        elif isinstance(cand, str):
                            peer.handle_ice_candidate(
                                int(data.get("sdpMLineIndex", 0)),
                                cand,
                            )
                    elif mtype == "quality":
                        q_info = peer.set_quality(str(data.get("quality", "high")))
                        runtime.quality = str(q_info["quality"])
                        await ws.send_json({"type": "quality_ack", **q_info})
                    elif mtype == "ping":
                        await ws.send_json(
                            {
                                "type": "pong",
                                "client_ts": data.get("client_ts"),
                                "server_ts": time.time() * 1000.0,
                            }
                        )
                    else:
                        # Fallback input handling over WebSocket if DataChannel isn't open yet
                        runtime.last_input_at = time.time()
                        if runtime.input_manager:
                            runtime.input_manager.handle_event(data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            if runtime.input_manager:
                runtime.input_manager.release_all_inputs()
            if runtime.active_peer is peer:
                peer.stop()
                runtime.active_peer = None
            if runtime.game_proc and runtime.game_proc.poll() is None:
                runtime.state = "ready"
            else:
                runtime.state = "ended"

        return ws

    app.router.add_get("/", handle_index)
    if (web_dir / "assets").exists():
        app.router.add_static("/assets", path=web_dir / "assets", show_index=False)
    app.router.add_get("/api/session/status", handle_status)
    app.router.add_post("/api/session/quality", handle_quality)
    app.router.add_post("/api/session/stop", handle_stop)
    app.router.add_get("/ws", handle_ws)
    return app


async def run_session_async(args: argparse.Namespace) -> int:
    game_cmd = shlex.split(args.game_cmd) if args.game_cmd else None
    runtime = IsolatedSessionRuntime(
        session_id=args.session_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
        quality=args.quality,
        game_cmd=game_cmd,
        port=args.port,
        user_id=args.user_id,
        app_id=args.app_id,
        display_num=getattr(args, "display_num", 0),
        launch_options=getattr(args, "launch_options", None),
    )

    state_dir = os.environ.get("SESSION_STATE_DIR")
    if state_dir and os.path.isdir(state_dir):
        iso_file = Path(state_dir) / "isolation.json"
        iso_file.write_text(json.dumps(runtime.isolation_report, indent=2))

    runtime._start_glib_loop()
    try:
        runtime.start_isolated_audio()
        runtime.start_isolated_display()
        runtime.start_game()
    except Exception as exc:
        logger.exception("Failed to initialize isolated session: %s", exc)
        runtime.state = "ended"
        runtime.error_message = str(exc)
        runtime.stop_all()
        return 1

    app = create_web_app(runtime)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=args.host, port=args.port)
    await site.start()

    logger.info(
        "Phase 1 Isolated Cloud Gaming Server ready at http://%s:%d (Session: %s)",
        args.host,
        args.port,
        args.session_id,
    )

    monitor_task = asyncio.create_task(runtime.monitor_game_lifecycle())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runtime._shutdown_event.set)
        except NotImplementedError:
            pass

    await runtime._shutdown_event.wait()
    monitor_task.cancel()
    if runtime.active_ws is not None and not runtime.active_ws.closed:
        try:
            await runtime.active_ws.close()
        except Exception:
            pass
    runtime.stop_all()
    try:
        await asyncio.wait_for(runner.cleanup(), timeout=2.0)
    except Exception:
        pass
    logger.info("Isolated session %s cleanly terminated and destroyed.", args.session_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Cloud Gaming Session Runner")
    parser.add_argument("--session-id", default="phase1-demo", help="Unique session identifier")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for HTTP/WebSocket server")
    parser.add_argument("--port", type=int, default=8080, help="Bind port for HTTP/WebSocket server")
    parser.add_argument("--width", type=int, default=1280, help="Stream width")
    parser.add_argument("--height", type=int, default=720, help="Stream height")
    parser.add_argument("--fps", type=int, default=60, help="Target stream framerate")
    parser.add_argument("--quality", default="high", choices=list(QUALITY_PRESETS.keys()))
    parser.add_argument("--user-id", default="default", help="User identifier for persistent saves/Steam profile")
    parser.add_argument("--app-id", default="0", help="Steam AppID or 0 for CyberArena 3D, 7 for Steam GamepadUI")
    parser.add_argument("--display-num", type=int, default=0, help="Explicit display number (0 = auto-detect free display)")
    parser.add_argument("--launch-options", default="", help="Steam launch options (e.g. WINEDLLOVERRIDES=... %%command%%)")
    parser.add_argument("--game-cmd", default="", help="Optional custom game command")
    args = parser.parse_args()

    return asyncio.run(run_session_async(args))


if __name__ == "__main__":
    sys.exit(main())

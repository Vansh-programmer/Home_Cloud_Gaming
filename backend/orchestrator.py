"""
Cloud Gaming Session Orchestrator, Concurrency Lock & Safety Watchdog (Phase 3).

Responsibilities:
1. Enforces the 1-session-at-a-time GPU lock across the PC and 1 session per user.
2. Spawns the isolated Bubblewrap container (engine/launch_phase2.py) bound strictly to
   127.0.0.1:<internal_port> so external clients can only access it through the authenticated proxy.
3. Manages the Session State Machine: starting -> ready -> playing -> ended with friendly progress & error messages.
4. Enforces Safety Limits:
   - Idle timeout: terminates sessions automatically after configurable inactivity.
   - Disconnect grace period: keeps the game running if the browser tab closes or Wi-Fi drops,
     allowing instant seamless reconnect within the grace window.
   - Admin force-end: immediately terminates any running session and releases the GPU lock.
5. Collects live NVIDIA RTX 4060 GPU telemetry (utilization %, VRAM usage, temperature °C).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from aiohttp import ClientSession, ClientTimeout

from backend.database import CloudGamingDatabase
from backend.network_manager import NetworkConfigManager
from engine.steam_manager import SteamLibraryManager
from engine.storage_manager import UserStorageManager, validate_user_id

logger = logging.getLogger("orchestrator")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FRIENDLY_END_MESSAGES = {
    "user_quit": "You ended the gaming session.",
    "game_exited": "The game closed normally and your isolated session was cleaned up.",
    "idle_timeout": "Session ended automatically due to inactivity (idle timeout).",
    "disconnect_timeout": "Session ended because the browser stayed disconnected past the reconnect grace window.",
    "admin_force_ended": "Session was ended by the server administrator.",
    "replaced_by_new_game": "Previous session was closed to launch your new game.",
    "startup_error": "The game container failed to initialize. Please try launching again.",
}


class SessionConflictError(Exception):
    """Raised when another user is currently using the gaming PC."""

    def __init__(self, active_username: str, active_game: str) -> None:
        self.active_username = active_username
        self.active_game = active_game
        super().__init__(
            f"Gaming PC is currently in use by {active_username} (playing {active_game}). "
            "Only one session can run at a time."
        )


def _find_free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class ManagedSession:
    session_id: str
    username: str
    app_id: str
    game_title: str
    quality: str
    width: int
    height: int
    fps: int
    internal_port: int
    process: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    ready_at: Optional[float] = None
    last_input_at: float = field(default_factory=time.time)
    disconnected_at: Optional[float] = None
    ended_at: Optional[float] = None
    state: str = "starting"  # starting | ready | playing | ended
    end_reason: Optional[str] = None
    error_message: Optional[str] = None
    client_connected: bool = False
    ever_connected: bool = False
    inner_status: Dict[str, object] = field(default_factory=dict)

    @property
    def internal_http_url(self) -> str:
        return f"http://127.0.0.1:{self.internal_port}"

    @property
    def internal_ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.internal_port}/ws"

    def stage_message(self, idle_timeout_sec: float, disconnect_grace_sec: float) -> str:
        if self.state == "starting":
            return f"Starting isolated sandbox & launching {self.game_title} on RTX 4060..."
        if self.state == "ready":
            if self.disconnected_at is not None:
                rem = max(0, int(disconnect_grace_sec - (time.time() - self.disconnected_at)))
                return f"Stream paused (disconnected). Reconnect within {rem}s to resume {self.game_title}."
            return f"{self.game_title} is ready! Connecting low-latency WebRTC stream..."
        if self.state == "playing":
            return f"Playing {self.game_title}"
        if self.state == "ended":
            if self.error_message:
                return self.error_message
            return FRIENDLY_END_MESSAGES.get(
                self.end_reason or "game_exited",
                "Session has ended and temporary container files were wiped.",
            )
        return ""

    def to_dict(self, idle_timeout_sec: float, disconnect_grace_sec: float) -> Dict[str, object]:
        now = time.time()
        idle_sec = round(max(0.0, now - self.last_input_at), 1) if self.state != "ended" else 0.0
        idle_remaining = (
            round(max(0.0, idle_timeout_sec - idle_sec), 1) if self.state != "ended" else 0.0
        )
        disconnect_remaining = (
            round(max(0.0, disconnect_grace_sec - (now - self.disconnected_at)), 1)
            if (self.disconnected_at is not None and self.state != "ended")
            else None
        )
        return {
            "session_id": self.session_id,
            "username": self.username,
            "app_id": self.app_id,
            "game_title": self.game_title,
            "quality": self.inner_status.get("quality", self.quality),
            "bitrate_kbps": self.inner_status.get("bitrate_kbps", 15000),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "state": self.state,
            "stage_message": self.stage_message(idle_timeout_sec, disconnect_grace_sec),
            "end_reason": self.end_reason,
            "error": self.error_message or self.inner_status.get("error"),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "uptime_sec": round((self.ended_at or now) - self.started_at, 1),
            "idle_sec": idle_sec,
            "idle_timeout_sec": idle_timeout_sec,
            "idle_remaining_sec": idle_remaining,
            "client_connected": self.client_connected,
            "disconnected_at": self.disconnected_at,
            "disconnect_grace_sec": disconnect_grace_sec,
            "disconnect_remaining_sec": disconnect_remaining,
            "savegame": self.inner_status.get("savegame"),
            "steam_login_remembered": self.inner_status.get("steam_login_remembered", False),
            "isolation": self.inner_status.get("isolation"),
        }


class SessionOrchestrator:
    """Central manager for isolated gaming sessions, concurrency locking, and safety timers."""

    def __init__(
        self,
        db: CloudGamingDatabase,
        storage_mgr: UserStorageManager,
        steam_mgr: SteamLibraryManager,
        idle_timeout_sec: float = 600.0,       # Default: 10 minutes
        disconnect_grace_sec: float = 300.0,   # Default: 5 minutes
        allow_pre_sandboxed: bool = False,
        network_mgr: Optional[NetworkConfigManager] = None,
        max_concurrent_sessions: Optional[int] = None,
    ) -> None:
        self.db = db
        self.storage_mgr = storage_mgr
        self.steam_mgr = steam_mgr
        self.network_mgr = network_mgr or NetworkConfigManager(data_root=storage_mgr.data_root)
        self.idle_timeout_sec = float(idle_timeout_sec)
        self.disconnect_grace_sec = float(disconnect_grace_sec)
        from engine.sandbox import EphemeralSandbox
        self.allow_pre_sandboxed = allow_pre_sandboxed or (
            os.environ.get("ALLOW_PRE_SANDBOXED_FALLBACK") == "1"
        ) or not EphemeralSandbox.can_use_bwrap()
        self.max_concurrent_sessions = int(
            max_concurrent_sessions
            if max_concurrent_sessions is not None
            else os.environ.get("MAX_CONCURRENT_SESSIONS", "1")
        )

        self._lock = asyncio.Lock()
        self.active_sessions: Dict[str, ManagedSession] = {}
        self.user_to_session: Dict[str, str] = {}
        self.last_ended_by_user: Dict[str, ManagedSession] = {}
        self.gpu_history: List[Dict[str, object]] = []
        self._last_telemetry_ts: float = 0.0
        self._watchdog_task: Optional[asyncio.Task] = None
        self._http_client: Optional[ClientSession] = None
        self._stopping = False

    @property
    def active_session(self) -> Optional[ManagedSession]:
        """Backward-compatible property returning the first active session."""
        for s in self.active_sessions.values():
            if s.state != "ended":
                return s
        return None

    @active_session.setter
    def active_session(self, val: Optional[ManagedSession]) -> None:
        if val is None:
            self.active_sessions.clear()
            self.user_to_session.clear()
        else:
            self.active_sessions[val.session_id] = val
            self.user_to_session[val.username] = val.session_id

    def get_managed_session_by_user(self, username: str) -> Optional[ManagedSession]:
        """Lookup active ManagedSession object for a given username."""
        clean_user = validate_user_id(username)
        sid = self.user_to_session.get(clean_user)
        if sid:
            s = self.active_sessions.get(sid)
            if s and s.state != "ended":
                return s
        return None

    def update_safety_settings(
        self,
        idle_timeout_sec: Optional[float] = None,
        disconnect_grace_sec: Optional[float] = None,
    ) -> Dict[str, float]:
        if idle_timeout_sec is not None:
            self.idle_timeout_sec = max(2.0, float(idle_timeout_sec))
        if disconnect_grace_sec is not None:
            self.disconnect_grace_sec = max(2.0, float(disconnect_grace_sec))
        return {
            "idle_timeout_sec": self.idle_timeout_sec,
            "disconnect_grace_sec": self.disconnect_grace_sec,
        }

    async def start(self) -> None:
        self._stopping = False
        self._http_client = ClientSession(timeout=ClientTimeout(total=1.5))
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        if self.active_sessions:
            for s in list(self.active_sessions.values()):
                await self._terminate_session_locked(s, reason="server_shutdown")
        if self._http_client:
            await self._http_client.close()
            self._http_client = None

    def get_active_session_public_summary(self) -> Optional[Dict[str, object]]:
        """Return safe summary of who is currently playing and available multiplayer slots."""
        actives = [s for s in self.active_sessions.values() if s.state != "ended"]
        if not actives:
            return None
        primary = actives[0]
        return {
            "session_id": primary.session_id,
            "username": primary.username,
            "app_id": primary.app_id,
            "game_title": primary.game_title,
            "state": primary.state,
            "started_at": primary.started_at,
            "uptime_sec": round(time.time() - primary.started_at, 1),
            "active_count": len(actives),
            "max_slots": self.max_concurrent_sessions,
            "slots_remaining": max(0, self.max_concurrent_sessions - len(actives)),
            "all_active": [
                {
                    "session_id": s.session_id,
                    "username": s.username,
                    "app_id": s.app_id,
                    "game_title": s.game_title,
                    "state": s.state,
                }
                for s in actives
            ],
        }

    def get_session_for_user(self, username: str) -> Optional[Dict[str, object]]:
        """Return the active session (or most recently ended session) for a specific user."""
        clean_user = validate_user_id(username)
        s = self.get_managed_session_by_user(clean_user)
        if s:
            return s.to_dict(self.idle_timeout_sec, self.disconnect_grace_sec)
        ended = self.last_ended_by_user.get(clean_user)
        if ended:
            return ended.to_dict(self.idle_timeout_sec, self.disconnect_grace_sec)
        return None

    async def start_or_reconnect_session(
        self,
        username: str,
        app_id: str = "0",
        quality: str = "high",
        width: int = 1280,
        height: int = 720,
        fps: int = 60,
        launch_options: Optional[str] = None,
    ) -> Dict[str, object]:
        """
        Start a new isolated session for `username` and `app_id`, or reconnect if `username`
        already has a running session for the same game.
        Raises SessionConflictError if active concurrent sessions reach capacity.
        """
        clean_user = validate_user_id(username)
        clean_app_id = str(app_id).strip() or "0"

        async with self._lock:
            # 1. Check if this specific user already has an active session
            user_sess = self.get_managed_session_by_user(clean_user)
            if user_sess is not None and user_sess.state != "ended":
                # Same user! If same app_id, reconnect seamlessly
                if user_sess.app_id == clean_app_id:
                    user_sess.last_input_at = time.time()
                    user_sess.disconnected_at = None
                    data = user_sess.to_dict(self.idle_timeout_sec, self.disconnect_grace_sec)
                    data["reconnected"] = True
                    return data
                # Same user switching to a different game: terminate previous session first
                await self._terminate_session_locked(user_sess, reason="replaced_by_new_game")

            # 2. Check if total active sessions across PC reached max capacity
            actives = [s for s in self.active_sessions.values() if s.state != "ended"]
            if len(actives) >= self.max_concurrent_sessions:
                primary = actives[0]
                raise SessionConflictError(
                    active_username=primary.username if len(actives) == 1 else ", ".join(s.username for s in actives),
                    active_game=primary.game_title if len(actives) == 1 else "All multiplayer slots in use",
                )

            game_entry = self.steam_mgr.get_game(clean_app_id)
            game_title = game_entry.title if game_entry else f"Steam App {clean_app_id}"

            internal_port = _find_free_loopback_port()
            session_id = f"cg-{clean_user}-{uuid.uuid4().hex[:6]}"

            launcher = str(PROJECT_ROOT / "engine" / "launch_phase2.py")
            cmd = [
                sys.executable,
                launcher,
                "--host",
                "127.0.0.1",
                "--port",
                str(internal_port),
                "--session-id",
                session_id,
                "--user",
                clean_user,
                "--app-id",
                clean_app_id,
                "--data-root",
                str(self.storage_mgr.data_root),
                "--width",
                str(width),
                "--height",
                str(height),
                "--fps",
                str(fps),
                "--quality",
                quality,
            ]
            if self.allow_pre_sandboxed:
                cmd.append("--allow-pre-sandboxed")

            effective_launch_opts = launch_options or self.steam_mgr.get_custom_launch_options(clean_app_id)
            if effective_launch_opts and str(effective_launch_opts).strip().lower() not in ("none", "null", ""):
                cmd.extend(["--launch-options", str(effective_launch_opts).strip()])

            env = os.environ.copy()
            if self.allow_pre_sandboxed:
                env["ALLOW_PRE_SANDBOXED_FALLBACK"] = "1"
            env.update(self.network_mgr.get_gstreamer_ice_env(clean_user))

            log_path = self.storage_mgr.data_root / f"session-{session_id}.log"
            log_fh = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
            log_fh.close()

            now = time.time()
            managed = ManagedSession(
                session_id=session_id,
                username=clean_user,
                app_id=clean_app_id,
                game_title=game_title,
                quality=quality,
                width=width,
                height=height,
                fps=fps,
                internal_port=internal_port,
                process=proc,
                started_at=now,
                last_input_at=now,
                state="starting",
            )
            self.active_sessions[session_id] = managed
            self.user_to_session[clean_user] = session_id
            self.db.record_session_start(
                session_id=session_id,
                username=clean_user,
                app_id=clean_app_id,
                game_title=game_title,
                quality=quality,
            )
            logger.info(
                "Spawned isolated session %s for user '%s' (game: %s) on 127.0.0.1:%d [%d/%d active]",
                session_id,
                clean_user,
                game_title,
                internal_port,
                len(self.active_sessions),
                self.max_concurrent_sessions,
            )
            data = managed.to_dict(self.idle_timeout_sec, self.disconnect_grace_sec)
            data["reconnected"] = False
            return data

    def notify_client_ws_connected(self, session_id: str) -> None:
        s = self.active_sessions.get(session_id)
        if s and s.state != "ended":
            now = time.time()
            s.client_connected = True
            s.ever_connected = True
            s.disconnected_at = None
            s.last_input_at = now
            s.state = "playing"
            self.db.update_session_state(session_id, "playing")

    def notify_client_ws_disconnected(self, session_id: str) -> None:
        s = self.active_sessions.get(session_id)
        if s and s.state != "ended":
            s.client_connected = False
            s.disconnected_at = time.time()
            if s.state == "playing":
                s.state = "ready"
                self.db.update_session_state(session_id, "ready")

    def notify_client_input(self, session_id: str) -> None:
        s = self.active_sessions.get(session_id)
        if s and s.state != "ended":
            s.last_input_at = time.time()

    async def terminate_session(
        self,
        reason: str = "user_quit",
        expected_username: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        async with self._lock:
            target: Optional[ManagedSession] = None
            if session_id:
                target = self.active_sessions.get(session_id)
            elif expected_username:
                clean_user = validate_user_id(expected_username)
                sid = self.user_to_session.get(clean_user)
                target = self.active_sessions.get(sid) if sid else None
            elif self.active_sessions:
                target = next(iter(self.active_sessions.values()))

            if target is None:
                return None

            if expected_username and target.username != validate_user_id(expected_username):
                raise PermissionError("You can only stop your own gaming session.")
            return await self._terminate_session_locked(target, reason=reason)

    async def _terminate_session_locked(self, s: ManagedSession, reason: str) -> Optional[Dict[str, object]]:
        if s is None:
            return None

        # Ask internal session runner to stop gracefully first
        if self._http_client and s.process.poll() is None:
            try:
                async with self._http_client.post(f"{s.internal_http_url}/api/session/stop") as _:
                    pass
                await asyncio.to_thread(s.process.wait, 2.5)
            except Exception:
                pass

        if s.process.poll() is None:
            try:
                s.process.terminate()
                await asyncio.to_thread(s.process.wait, 2.0)
            except Exception:
                try:
                    s.process.kill()
                    await asyncio.to_thread(s.process.wait, 1.0)
                except Exception:
                    pass

        log_path = self.storage_mgr.data_root / f"session-{s.session_id}.log"
        if log_path.exists() and reason in ("user_quit", "server_shutdown"):
            try:
                log_path.unlink()
            except OSError:
                pass

        s.state = "ended"
        s.client_connected = False
        s.ended_at = time.time()
        s.end_reason = reason
        self.db.record_session_end(s.session_id, end_reason=reason, started_at=s.started_at)
        self.last_ended_by_user[s.username] = s
        self.active_sessions.pop(s.session_id, None)
        if self.user_to_session.get(s.username) == s.session_id:
            self.user_to_session.pop(s.username, None)
        logger.info("Session %s for user '%s' ended (reason: %s)", s.session_id, s.username, reason)
        return s.to_dict(self.idle_timeout_sec, self.disconnect_grace_sec)

    async def _terminate_locked(self, reason: str) -> Optional[Dict[str, object]]:
        s = self.active_session
        if s is None:
            return None
        return await self._terminate_session_locked(s, reason=reason)

    async def _watchdog_loop(self) -> None:
        """Continuously monitor active session processes, sync status, and enforce timeouts."""
        while not self._stopping:
            try:
                await self._watchdog_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Watchdog tick warning: %s", exc)
            await asyncio.sleep(0.35)

    async def _watchdog_tick(self) -> None:
        if not self.active_sessions:
            return

        now = time.time()
        for s in list(self.active_sessions.values()):
            if s.state == "ended":
                continue

            # 1. Check if container process exited on its own (e.g. player quit inside game)
            ret = s.process.poll()
            if ret is not None:
                async with self._lock:
                    if s.session_id in self.active_sessions:
                        reason = "game_exited" if ret == 0 else "startup_error"
                        if ret != 0 and s.state == "starting":
                            log_path = self.storage_mgr.data_root / f"session-{s.session_id}.log"
                            tail_msg = ""
                            if log_path.exists():
                                try:
                                    lines = [line.strip() for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
                                    if lines:
                                        tail_msg = f": {lines[-1]}"
                                except Exception:
                                    pass
                            s.error_message = f"Game container exited with code {ret} during startup{tail_msg}"
                        await self._terminate_session_locked(s, reason=reason)
                continue

            # 2. Poll internal container /api/session/status
            if self._http_client:
                try:
                    async with self._http_client.get(f"{s.internal_http_url}/api/session/status") as resp:
                        if resp.status == 200:
                            st = await resp.json()
                            s.inner_status = st
                            inner_last_input = float(st.get("last_input_at", 0.0))
                            if inner_last_input > s.last_input_at:
                                s.last_input_at = inner_last_input

                            inner_state = str(st.get("state", "starting"))
                            if s.state == "starting" and inner_state in ("ready", "playing"):
                                s.state = "playing" if s.client_connected else "ready"
                                s.ready_at = now
                                s.last_input_at = max(s.last_input_at, now)
                                self.db.update_session_state(s.session_id, s.state)
                except Exception:
                    pass

            # 3. Enforce Idle Timeout (only once session has finished starting)
            if s.state in ("ready", "playing"):
                idle_elapsed = now - s.last_input_at
                if idle_elapsed >= self.idle_timeout_sec:
                    logger.info(
                        "Session %s exceeded idle timeout (%.1fs >= %.1fs); terminating",
                        s.session_id,
                        idle_elapsed,
                        self.idle_timeout_sec,
                    )
                    async with self._lock:
                        if s.session_id in self.active_sessions:
                            await self._terminate_session_locked(s, reason="idle_timeout")
                    continue

            # 4. Enforce Disconnect Grace Timeout
            if s.disconnected_at is not None:
                disc_elapsed = now - s.disconnected_at
                if disc_elapsed >= self.disconnect_grace_sec:
                    logger.info(
                        "Session %s exceeded disconnect grace window (%.1fs >= %.1fs); terminating",
                        s.session_id,
                        disc_elapsed,
                        self.disconnect_grace_sec,
                    )
                    async with self._lock:
                        if s.session_id in self.active_sessions:
                            await self._terminate_session_locked(s, reason="disconnect_timeout")
                    continue

    @staticmethod
    def _parse_float(val: str, default: float = 0.0) -> float:
        try:
            return float(val.strip())
        except Exception:
            return default

    @classmethod
    def get_gpu_telemetry(cls) -> Dict[str, object]:
        """Query live NVIDIA GPU load, NVENC encoder load, VRAM usage, power, and temperature via nvidia-smi."""
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,utilization.encoder,utilization.decoder,fan.speed",
                    "--format=csv,noheader,nounits",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
                if len(parts) >= 7:
                    vram_used = cls._parse_float(parts[4], 0.0)
                    vram_total = cls._parse_float(parts[5], 8188.0)
                    vram_pct = round((vram_used / vram_total) * 100.0, 1) if vram_total > 0 else 0.0
                    temp_c = cls._parse_float(parts[6], 0.0)
                    thermal_state = "optimal" if temp_c < 70 else ("warm" if temp_c < 82 else "hot")
                    return {
                        "available": True,
                        "name": parts[0],
                        "driver_version": parts[1],
                        "gpu_util_percent": cls._parse_float(parts[2], 0.0),
                        "mem_util_percent": cls._parse_float(parts[3], 0.0),
                        "vram_used_mb": vram_used,
                        "vram_total_mb": vram_total,
                        "vram_percent": vram_pct,
                        "temperature_c": temp_c,
                        "thermal_state": thermal_state,
                        "power_watts": cls._parse_float(parts[7], 0.0) if len(parts) > 7 else None,
                        "power_limit_watts": cls._parse_float(parts[8], 115.0) if len(parts) > 8 else None,
                        "encoder_util_percent": cls._parse_float(parts[9], 0.0) if len(parts) > 9 else 0.0,
                        "decoder_util_percent": cls._parse_float(parts[10], 0.0) if len(parts) > 10 else 0.0,
                        "fan_speed_percent": cls._parse_float(parts[11], 0.0) if len(parts) > 11 else 0.0,
                    }
        except Exception:
            pass
        return {
            "available": False,
            "name": "NVIDIA GeForce RTX 4060",
            "driver_version": "unknown",
            "gpu_util_percent": 0.0,
            "mem_util_percent": 0.0,
            "vram_used_mb": 0.0,
            "vram_total_mb": 8188.0,
            "vram_percent": 0.0,
            "temperature_c": 0.0,
            "thermal_state": "optimal",
            "power_watts": None,
            "power_limit_watts": None,
            "encoder_util_percent": 0.0,
            "decoder_util_percent": 0.0,
            "fan_speed_percent": 0.0,
        }

    def sample_gpu_telemetry(self) -> Dict[str, object]:
        """Collect current GPU telemetry and append to the rolling 60-sample history buffer."""
        now = time.time()
        gpu = self.get_gpu_telemetry()
        if now - self._last_telemetry_ts >= 1.5 or not self.gpu_history:
            self._last_telemetry_ts = now
            self.gpu_history.append(
                {
                    "ts": round(now, 1),
                    "gpu_util": gpu["gpu_util_percent"],
                    "enc_util": gpu["encoder_util_percent"],
                    "temp_c": gpu["temperature_c"],
                    "vram_pct": gpu["vram_percent"],
                }
            )
            if len(self.gpu_history) > 60:
                self.gpu_history = self.gpu_history[-60:]
        return gpu

    def get_host_telemetry(self) -> Dict[str, object]:
        """Collect host CPU load, RAM usage, and disk space on the storage partition."""
        cpu_count = os.cpu_count() or 12
        try:
            load1, load5, _load15 = os.getloadavg()
        except OSError:
            load1, load5 = 0.0, 0.0

        ram_total_gb = 16.0
        ram_avail_gb = 8.0
        try:
            meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    ram_total_gb = round(int(line.split()[1]) / (1024 * 1024), 2)
                elif line.startswith("MemAvailable:"):
                    ram_avail_gb = round(int(line.split()[1]) / (1024 * 1024), 2)
        except Exception:
            pass
        ram_used_gb = round(max(0.0, ram_total_gb - ram_avail_gb), 2)
        ram_percent = round((ram_used_gb / ram_total_gb) * 100.0, 1) if ram_total_gb > 0 else 0.0

        try:
            du = shutil.disk_usage(self.storage_mgr.data_root)
            disk_total_gb = round(du.total / (1024 ** 3), 1)
            disk_used_gb = round(du.used / (1024 ** 3), 1)
            disk_free_gb = round(du.free / (1024 ** 3), 1)
            disk_percent = round((du.used / du.total) * 100.0, 1) if du.total > 0 else 0.0
        except Exception:
            disk_total_gb, disk_used_gb, disk_free_gb, disk_percent = 220.0, 44.0, 176.0, 20.0

        return {
            "cpu_cores": cpu_count,
            "load_1m": round(load1, 2),
            "load_5m": round(load5, 2),
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "ram_percent": ram_percent,
            "disk_used_gb": disk_used_gb,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
            "disk_percent": disk_percent,
        }


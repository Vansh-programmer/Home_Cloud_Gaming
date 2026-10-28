"""
Strict Ephemeral Container Sandbox using Bubblewrap (bwrap).

Enforces the #1 security rule:
- Each play session runs in its own isolated environment that is deleted when the session ends.
- The session never sees or reaches the host desktop, host files (/home/vansh), other apps,
  host X11/Wayland sockets, host audio devices, physical keyboard/mouse devices, or other sessions.
- Never uses privileged Docker containers or host namespace sharing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SandboxConfig:
    session_id: str
    width: int = 1920
    height: int = 1080
    fps: int = 60
    user_id: str = "default"
    app_id: str = "0"
    # Optional read-only game directory to mount at /game inside the container
    game_dir: Optional[Path] = None
    # Shared read-only base Steam library mounted at /steam_shared (:ro)
    shared_steam_dir: Optional[Path] = None
    # Per-user persistent directories (Phase 2+: Steam login tokens, Proton prefixes, game saves)
    user_persist_dir: Optional[Path] = None
    user_steam_dot_dir: Optional[Path] = None
    user_steam_dir: Optional[Path] = None
    user_local_share_dir: Optional[Path] = None
    user_config_dir: Optional[Path] = None
    # Extra read-only binds if needed
    extra_ro_binds: Dict[str, str] = field(default_factory=dict)


class EphemeralSandbox:
    """Manages an isolated, ephemeral Bubblewrap container for a single gaming session."""

    def __init__(self, config: SandboxConfig) -> None:
        self.config = config
        self.session_root = Path(f"/tmp/cloudgaming-session-{config.session_id}")
        self.runtime_dir = self.session_root / "runtime"
        self.home_dir = self.session_root / "home"
        self.tmp_dir = self.session_root / "tmp"

    def prepare_directories(self) -> None:
        """Create isolated ephemeral directories on the host with 0700 permissions."""
        if self.session_root.exists():
            shutil.rmtree(self.session_root, ignore_errors=True)

        self.session_root.mkdir(parents=True, mode=0o700)
        self.runtime_dir.mkdir(parents=True, mode=0o700)
        self.home_dir.mkdir(parents=True, mode=0o700)
        self.tmp_dir.mkdir(parents=True, mode=0o700)
        x11_unix = self.tmp_dir / ".X11-unix"
        x11_unix.mkdir(parents=True, mode=0o1777)
        os.chmod(x11_unix, 0o1777)

    def cleanup(self) -> None:
        """Destroy all ephemeral session directories and leftover state."""
        if self.session_root.exists():
            shutil.rmtree(self.session_root, ignore_errors=True)

    @staticmethod
    def can_use_bwrap() -> bool:
        """Check whether bubblewrap can create user/mount namespaces in the current environment."""
        if not shutil.which("bwrap"):
            return False
        try:
            res = subprocess.run(
                [
                    "bwrap",
                    "--unshare-user",
                    "--unshare-pid",
                    "--unshare-ipc",
                    "--unshare-uts",
                    "--ro-bind",
                    "/usr",
                    "/usr",
                    "--symlink",
                    "usr/lib",
                    "/lib",
                    "--symlink",
                    "usr/lib",
                    "/lib64",
                    "--symlink",
                    "usr/bin",
                    "/bin",
                    "--proc",
                    "/proc",
                    "--dev",
                    "/dev",
                    "/usr/bin/true",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )
            return res.returncode == 0
        except Exception:
            return False

    def build_bwrap_command(self, inner_cmd: List[str], env_vars: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Construct the strict unprivileged bwrap command line.
        - Unshares user, IPC, PID, UTS, and cgroup namespaces.
        - Clears all host environment variables (--clearenv).
        - Creates a fresh minimal /dev and binds ONLY NVIDIA/DRM GPU device nodes.
        - Never exposes /home/<host_user>, /tmp/.X11-unix, /run/user/<uid>, /dev/input, or /dev/snd.
        """
        cmd: List[str] = [
            "bwrap",
            "--unshare-user",
            "--unshare-ipc",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--hostname", f"cg-{self.config.session_id[:8]}",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            # Read-only system binaries & libraries (including 32-bit multilib for Steam/Proton)
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib", "/lib64",
            "--symlink", "usr/lib32", "/lib32",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/bin", "/sbin",
            # Minimal /proc, read-only /sys, and isolated /dev with writable /dev/shm for CUDA & PulseAudio
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/dev/shm",
            "--ro-bind", "/sys", "/sys",
            # Ephemeral tmpfs mounts for /tmp, /run, /var, /home
            "--tmpfs", "/tmp",
            "--tmpfs", "/run",
            "--tmpfs", "/var",
            "--tmpfs", "/home",
            "--dir", "/home/gamer",
            "--dir", "/tmp/runtime",
            "--chmod", "0700", "/tmp/runtime",
            "--dir", "/tmp/.X11-unix",
            "--chmod", "1777", "/tmp/.X11-unix",
        ]

        # Safe read-only /etc files needed for DNS, SSL, fonts, dynamic linker, NSS, and Vulkan/NVIDIA ICDs
        safe_etc_paths = [
            "/etc/passwd",
            "/etc/group",
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            "/etc/ld.so.conf.d",
            "/etc/fonts",
            "/etc/ssl",
            "/etc/ca-certificates",
            "/etc/resolv.conf",
            "/etc/hosts",
            "/etc/nsswitch.conf",
            "/etc/localtime",
            "/etc/machine-id",
            "/etc/nvidia",
            "/etc/vulkan",
            "/etc/glvnd",
            "/etc/egl",
            "/etc/gbm",
            "/etc/X11",
            "/etc/xdg",
            "/etc/pipewire",
            "/etc/pulse",
            "/etc/alsa",
            "/etc/dbus-1",
        ]
        for etc_path in safe_etc_paths:
            if os.path.exists(etc_path):
                cmd.extend(["--ro-bind-try", etc_path, etc_path])

        # Bind systemd DNS resolver directory read-only if present for systemd-resolved hosts
        if os.path.exists("/run/systemd/resolve"):
            cmd.extend(["--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve"])

        # Bind ONLY GPU device nodes (/dev/dri and /dev/nvidia*) - NEVER /dev/input or /dev/snd
        gpu_dev_paths = [
            "/dev/dri",
            "/dev/nvidia0",
            "/dev/nvidiactl",
            "/dev/nvidia-modeset",
            "/dev/nvidia-uvm",
            "/dev/nvidia-uvm-tools",
            "/dev/nvidia-caps",
        ]
        for dev_path in gpu_dev_paths:
            if os.path.exists(dev_path):
                cmd.extend(["--dev-bind-try", dev_path, dev_path])

        # Mount ONLY the engine and web asset directories read-only at /opt/cloudgaming
        # (Never mount backend databases or host home directories into the container)
        project_root = Path(__file__).resolve().parent.parent
        cmd.extend(["--dir", "/opt/cloudgaming"])
        cmd.extend(["--ro-bind", str(project_root / "engine"), "/opt/cloudgaming/engine"])
        if (project_root / "web").exists():
            cmd.extend(["--ro-bind", str(project_root / "web"), "/opt/cloudgaming/web"])

        # Mount session communication socket/state directory at /run/session
        cmd.extend(["--bind", str(self.runtime_dir), "/run/session"])

        # Mount optional read-only game directory
        if self.config.game_dir and self.config.game_dir.exists():
            cmd.extend(["--ro-bind", str(self.config.game_dir), "/game"])

        # Mount shared Steam library strictly READ-ONLY at /steam_shared
        has_extra_steam_binds = any(
            dst.startswith("/steam_shared") for dst in self.config.extra_ro_binds.values()
        )
        if has_extra_steam_binds:
            # When host library games are bound inside /steam_shared, mount /steam_shared as a tmpfs,
            # bind individual items, and remount-ro so bwrap does not fail with "Read-only file system".
            cmd.extend([
                "--tmpfs", "/steam_shared",
                "--dir", "/steam_shared/steamapps",
                "--dir", "/steam_shared/steamapps/common",
            ])
            if self.config.shared_steam_dir and self.config.shared_steam_dir.exists():
                shared_steamapps = self.config.shared_steam_dir / "steamapps"
                if shared_steamapps.exists():
                    for item in shared_steamapps.iterdir():
                        if item.name == "common" and item.is_dir():
                            for c_item in item.iterdir():
                                cmd.extend(["--ro-bind", str(c_item), f"/steam_shared/steamapps/common/{c_item.name}"])
                        else:
                            cmd.extend(["--ro-bind", str(item), f"/steam_shared/steamapps/{item.name}"])
            for src, dst in self.config.extra_ro_binds.items():
                if dst.startswith("/steam_shared") and os.path.exists(src):
                    cmd.extend(["--ro-bind", src, dst])
            cmd.extend(["--remount-ro", "/steam_shared"])
        elif self.config.shared_steam_dir and self.config.shared_steam_dir.exists():
            cmd.extend(["--ro-bind", str(self.config.shared_steam_dir), "/steam_shared"])

        # Allow Proton to acquire its runtime lock without triggering Read-only file system error
        for src, dst in self.config.extra_ro_binds.items():
            if "proton" in dst.lower() and dst.startswith("/steam_shared") and os.path.isdir(src):
                lock_file_src = Path(src) / "dist.lock"
                try:
                    lock_file_src.touch(exist_ok=True)
                except Exception:
                    pass
                lock_name = "proton_" + re.sub(r"[^a-zA-Z0-9_]", "_", dst) + ".lock"
                lock_file = self.tmp_dir / lock_name
                lock_file.touch(mode=0o666, exist_ok=True)
                cmd.extend(["--bind", str(lock_file), f"{dst}/dist.lock"])

        if self.config.shared_steam_dir and self.config.shared_steam_dir.exists():
            common_dir = self.config.shared_steam_dir / "steamapps" / "common"
            if common_dir.exists():
                for p in common_dir.glob("Proton*"):
                    if p.is_dir():
                        lock_file_src = p / "dist.lock"
                        try:
                            lock_file_src.touch(exist_ok=True)
                        except Exception:
                            pass
                        lock_name = "proton_" + re.sub(r"[^a-zA-Z0-9_]", "_", p.name) + ".lock"
                        lock_file = self.tmp_dir / lock_name
                        lock_file.touch(mode=0o666, exist_ok=True)
                        cmd.extend(["--bind", str(lock_file), f"/steam_shared/steamapps/common/{p.name}/dist.lock"])

        # Mount optional per-user persistent directories (Phase 2+: Steam login tokens, Proton prefixes, saves)
        if self.config.user_persist_dir and self.config.user_persist_dir.exists():
            cmd.extend(["--bind", str(self.config.user_persist_dir), "/home/gamer/persist"])
        steam_dot = self.config.user_steam_dot_dir or self.config.user_steam_dir
        if steam_dot and steam_dot.exists():
            cmd.extend(["--bind", str(steam_dot), "/home/gamer/.steam"])
        if self.config.user_local_share_dir and self.config.user_local_share_dir.exists():
            cmd.extend(["--dir", "/home/gamer/.local"])
            cmd.extend(["--bind", str(self.config.user_local_share_dir), "/home/gamer/.local/share"])
        if self.config.user_config_dir and self.config.user_config_dir.exists():
            cmd.extend(["--bind", str(self.config.user_config_dir), "/home/gamer/.config"])

        for src, dst in self.config.extra_ro_binds.items():
            if not dst.startswith("/steam_shared") and os.path.exists(src):
                cmd.extend(["--ro-bind", src, dst])

        # Set strict, clean environment variables inside the container
        default_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/gamer",
            "USER": "gamer",
            "LOGNAME": "gamer",
            "XDG_RUNTIME_DIR": "/tmp/runtime",
            "XDG_DATA_HOME": "/home/gamer/.local/share",
            "XDG_CONFIG_HOME": "/home/gamer/.config",
            "XDG_CURRENT_DESKTOP": "gamescope",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "STREAM_WIDTH": str(self.config.width),
            "STREAM_HEIGHT": str(self.config.height),
            "STREAM_FPS": str(self.config.fps),
            "SESSION_ID": self.config.session_id,
            "SESSION_STATE_DIR": "/run/session",
            "CLOUD_USER_ID": self.config.user_id,
            "CLOUD_APP_ID": self.config.app_id,
            "SANDBOX_MODE": "bwrap-strict",
            "STUN_SERVER": os.environ.get("STUN_SERVER", ""),
            "TURN_SERVER": os.environ.get("TURN_SERVER", ""),
            "TURN_SERVERS": os.environ.get("TURN_SERVERS", ""),
            "RTP_MIN_PORT": os.environ.get("RTP_MIN_PORT", "30000"),
            "RTP_MAX_PORT": os.environ.get("RTP_MAX_PORT", "60000"),
            "PRESSURE_VESSEL_FILESYSTEMS_RO": "/steam_shared:/game",
            "STEAM_COMPAT_MOUNTS": "/steam_shared:/game",
            "STEAM_COMPAT_LIBRARY_PATHS": "/home/gamer/.local/share/Steam:/steam_shared",
            "DXVK_FRAME_RATE": str(self.config.fps),
            "DXVK_ASYNC": "1",
            "__GL_MaxFramesAllowed": "1",
            "__GL_THREADED_OPTIMIZATIONS": "1",
            "__GL_SYNC_TO_VBLANK": "0",
            "PROTON_ENABLE_NVAPI": "1",
            "PROTON_HIDE_NVIDIA_GPU": "0",
            "PIPEWIRE_LATENCY": "128/48000",
            "PULSE_LATENCY_MSEC": "10",
            "vblank_mode": "0",
            "STEAM_DISABLE_SANDBOX": "1",
            "STEAM_NO_CEF_SANDBOX": "1",
            "STEAM_ZENITY": "0",
            "SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS": "0",
        }
        if env_vars:
            default_env.update(env_vars)

        for k, v in default_env.items():
            cmd.extend(["--setenv", k, v])

        cmd.extend(["--chdir", "/home/gamer"])
        cmd.append("--")
        cmd.extend(inner_cmd)
        return cmd


def run_isolation_self_check(host_user: str = "vansh") -> Dict[str, object]:
    """
    Inspect the current environment from inside a session to verify that host desktop,
    host home directory, physical input devices, and host audio sockets are unreachable.
    """
    host_home = Path(f"/home/{host_user}")
    host_x0 = Path("/tmp/.X11-unix/X0")
    host_runtime = Path(f"/run/user/{os.getuid()}") if os.getuid() != 0 else Path("/run/user/1000")
    dev_input_by_id = Path("/dev/input/by-id")
    dev_snd = Path("/dev/snd")
    gpu_render = Path("/dev/dri/renderD128")
    nvidia_ctl = Path("/dev/nvidiactl")

    host_home_accessible = host_home.exists() and any(host_home.iterdir()) if host_home.exists() else False
    host_x0_accessible = host_x0.exists()
    host_runtime_accessible = host_runtime.exists() and (host_runtime / "wayland-0").exists()
    physical_inputs_accessible = dev_input_by_id.exists()
    host_sound_accessible = dev_snd.exists()
    gpu_accessible = gpu_render.exists() or nvidia_ctl.exists()

    # Check shared Steam library is strictly read-only if mounted
    steam_shared = Path("/steam_shared")
    if steam_shared.exists():
        shared_library_readonly = not os.access(steam_shared, os.W_OK)
    else:
        shared_library_readonly = True

    data_home = Path(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")))
    user_storage_writable = data_home.exists() and os.access(data_home, os.W_OK)

    checks = {
        "sandbox_mode": os.environ.get("SANDBOX_MODE", "unknown"),
        "user_id": os.environ.get("CLOUD_USER_ID", "default"),
        "app_id": os.environ.get("CLOUD_APP_ID", "0"),
        "isolated_home": os.environ.get("HOME", ""),
        "isolated_xdg_runtime": os.environ.get("XDG_RUNTIME_DIR", ""),
        "host_home_inaccessible": not host_home_accessible,
        "host_x11_inaccessible": not host_x0_accessible,
        "host_wayland_inaccessible": not host_runtime_accessible,
        "physical_inputs_inaccessible": not physical_inputs_accessible,
        "host_soundcard_inaccessible": not host_sound_accessible,
        "gpu_accessible": gpu_accessible,
        "shared_library_readonly": shared_library_readonly,
        "user_storage_writable": user_storage_writable,
    }
    checks["all_passed"] = all(
        [
            checks["host_home_inaccessible"],
            checks["host_x11_inaccessible"],
            checks["host_wayland_inaccessible"],
            checks["physical_inputs_inaccessible"],
            checks["host_soundcard_inaccessible"],
            checks["gpu_accessible"],
            checks["shared_library_readonly"],
        ]
    )
    return checks


if __name__ == "__main__":
    print(json.dumps(run_isolation_self_check(), indent=2))

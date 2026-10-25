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
    width: int = 1280
    height: int = 720
    fps: int = 60
    # Optional read-only game directory to mount at /game inside the container
    game_dir: Optional[Path] = None
    # Optional per-user persistent directory (used in Phase 2+ for Steam/saves)
    user_persist_dir: Optional[Path] = None
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
        # Sweep any orphaned session directories from previous hard kills
        for stale in Path("/tmp").glob("cloudgaming-session-*"):
            if stale != self.session_root:
                shutil.rmtree(stale, ignore_errors=True)

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
            "--uid", "0",
            "--gid", "0",
            "--unshare-ipc",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--hostname", f"cg-{self.config.session_id[:8]}",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            # Read-only system binaries & libraries
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib", "/lib64",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/bin", "/sbin",
            # Minimal /proc, /sys (read-only), and isolated /dev
            "--proc", "/proc",
            "--dev", "/dev",
            "--ro-bind-try", "/sys/dev", "/sys/dev",
            "--ro-bind-try", "/sys/devices", "/sys/devices",
            "--ro-bind-try", "/sys/bus", "/sys/bus",
            "--ro-bind-try", "/sys/class/drm", "/sys/class/drm",
            # Ephemeral tmpfs mounts for /tmp, /run, /var, /home
            "--tmpfs", "/tmp",
            "--tmpfs", "/run",
            "--tmpfs", "/var",
            "--tmpfs", "/home",
            "--dir", "/home/gamer",
            "--dir", "/run/user/0",
            "--chmod", "0700", "/run/user/0",
            "--dir", "/tmp/.X11-unix",
            "--chmod", "1777", "/tmp/.X11-unix",
        ]

        # Safe read-only /etc files needed for DNS, SSL, fonts, dynamic linker, and Vulkan ICDs
        safe_etc_paths = [
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
            "/etc/vulkan",
            "/etc/glvnd",
            "/etc/egl",
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

        # Mount optional per-user persistent directory
        if self.config.user_persist_dir and self.config.user_persist_dir.exists():
            cmd.extend(["--bind", str(self.config.user_persist_dir), "/home/gamer/persist"])

        for src, dst in self.config.extra_ro_binds.items():
            if os.path.exists(src):
                cmd.extend(["--ro-bind", src, dst])

        # Set strict, clean environment variables inside the container
        default_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/gamer",
            "USER": "gamer",
            "LOGNAME": "gamer",
            "XDG_RUNTIME_DIR": "/run/user/0",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "STREAM_WIDTH": str(self.config.width),
            "STREAM_HEIGHT": str(self.config.height),
            "STREAM_FPS": str(self.config.fps),
            "SESSION_ID": self.config.session_id,
            "SESSION_STATE_DIR": "/run/session",
            "SANDBOX_MODE": "bwrap-strict",
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

    checks = {
        "sandbox_mode": os.environ.get("SANDBOX_MODE", "unknown"),
        "isolated_home": os.environ.get("HOME", ""),
        "isolated_xdg_runtime": os.environ.get("XDG_RUNTIME_DIR", ""),
        "host_home_inaccessible": not host_home_accessible,
        "host_x11_inaccessible": not host_x0_accessible,
        "host_wayland_inaccessible": not host_runtime_accessible,
        "physical_inputs_inaccessible": not physical_inputs_accessible,
        "host_soundcard_inaccessible": not host_sound_accessible,
        "gpu_accessible": gpu_accessible,
    }
    checks["all_passed"] = all(
        [
            checks["host_home_inaccessible"],
            checks["host_x11_inaccessible"],
            checks["host_wayland_inaccessible"],
            checks["physical_inputs_inaccessible"],
            checks["host_soundcard_inaccessible"],
            checks["gpu_accessible"],
        ]
    )
    return checks


if __name__ == "__main__":
    print(json.dumps(run_isolation_self_check(), indent=2))

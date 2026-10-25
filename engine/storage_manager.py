"""
Per-User Persistent Storage & Shared Read-Only Steam Library Manager (Phase 2).

Enforces storage isolation rules:
1. Shared base Steam library is mounted strictly READ-ONLY (/steam_shared) inside containers
   so users cannot modify shared game binaries/assets or waste disk space.
2. Each user gets an isolated persistent directory tree on the host (data/users/<user_id>/)
   mounted into /home/gamer/.steam, /home/gamer/.local/share, and /home/gamer/.config.
3. User A can never see or access User B's Steam login tokens, Proton prefixes, or game saves.
4. Steam passwords are never seen or stored by our website; Steam's own encrypted login tokens
   (config/config.vdf, config/loginusers.vdf, userdata/) persist inside the user's Steam directory.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

VALID_USER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}$")


def validate_user_id(user_id: str) -> str:
    """Validate user_id to prevent path traversal, CLI flag injection, or invalid directory names."""
    clean = user_id.strip()
    if not VALID_USER_RE.match(clean):
        raise ValueError(
            f"Invalid user_id '{user_id}'. Must be 2-32 alphanumeric, underscore, or hyphen characters starting with alphanumeric."
        )
    return clean.lower()


@dataclass
class UserStoragePaths:
    user_id: str
    user_root: Path
    steam_dot_dir: Path       # Mounted at /home/gamer/.steam
    local_share_dir: Path     # Mounted at /home/gamer/.local/share
    config_dir: Path          # Mounted at /home/gamer/.config
    steam_root_dir: Path      # /home/gamer/.local/share/Steam (inside local_share_dir)
    cyberarena_save_file: Path
    shared_steam_dir: Optional[Path] = None

    @property
    def steam_dir(self) -> Path:
        return self.steam_dot_dir


class UserStorageManager:
    """Manages shared read-only game libraries and per-user persistent overlays/saves."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.data_root = (data_root or (project_root / "data")).resolve()
        self.users_root = self.data_root / "users"
        self.shared_steam_dir = self.data_root / "shared_steam_library"

    def ensure_base_directories(self) -> None:
        """Ensure top-level data/users and data/shared_steam_library exist."""
        self.users_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.users_root, 0o700)

        steamapps = self.shared_steam_dir / "steamapps" / "common"
        steamapps.mkdir(parents=True, exist_ok=True)

    def prepare_user_storage(self, user_id: str) -> UserStoragePaths:
        """
        Create and initialize isolated persistent directories for a specific user.
        Links shared read-only Steam games into the user's Steam directory while keeping
        config/, userdata/, compatdata/, and game saves writable per-user.
        """
        uid = validate_user_id(user_id)
        self.ensure_base_directories()

        user_root = self.users_root / uid
        home_persist = user_root / "home"
        steam_dot_dir = home_persist / ".steam"
        local_share_dir = home_persist / ".local" / "share"
        config_dir = home_persist / ".config"
        steam_root_dir = local_share_dir / "Steam"

        for d in (
            user_root,
            home_persist,
            steam_dot_dir,
            local_share_dir,
            config_dir,
            steam_root_dir,
            steam_root_dir / "config",
            steam_root_dir / "userdata",
            steam_root_dir / "logs",
            steam_root_dir / "steamapps",
            steam_root_dir / "steamapps" / "common",
            steam_root_dir / "steamapps" / "compatdata",
            steam_root_dir / "steamapps" / "shadercache",
            local_share_dir / "cyberarena",
        ):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(user_root, 0o700)

        # Remove any stale PulseAudio runtime symlink from previous ephemeral containers
        shutil.rmtree(config_dir / "pulse", ignore_errors=True)

        # Ensure standard ~/.steam/steam and ~/.steam/root relative symlinks point to ../.local/share/Steam
        # Using a relative symlink works both inside bwrap (/home/gamer/.steam -> /home/gamer/.local/share/Steam)
        # and on the host / pre-sandboxed environment.
        rel_steam_path = "../.local/share/Steam"
        for link_name in ("steam", "root"):
            link_path = steam_dot_dir / link_name
            if link_path.is_symlink() or link_path.exists():
                if link_path.is_symlink() and os.readlink(link_path) == rel_steam_path:
                    continue
                if link_path.is_symlink() or link_path.is_file():
                    link_path.unlink()
            if not link_path.exists():
                os.symlink(rel_steam_path, link_path)

        # Configure libraryfolders.vdf so Steam inside the container recognizes /steam_shared
        self._write_libraryfolders_vdf(steam_root_dir / "steamapps" / "libraryfolders.vdf")

        # Link any shared appmanifests and common game folders into the user's steamapps
        self._sync_shared_library_links(steam_root_dir / "steamapps")

        return UserStoragePaths(
            user_id=uid,
            user_root=user_root,
            steam_dot_dir=steam_dot_dir,
            local_share_dir=local_share_dir,
            config_dir=config_dir,
            steam_root_dir=steam_root_dir,
            cyberarena_save_file=local_share_dir / "cyberarena" / "savegame.json",
            shared_steam_dir=self.shared_steam_dir,
        )

    def _write_libraryfolders_vdf(self, vdf_path: Path) -> None:
        if vdf_path.exists():
            return
        content = (
            '"libraryfolders"\n'
            "{\n"
            '\t"0"\n'
            "\t{\n"
            '\t\t"path"\t\t"/home/gamer/.local/share/Steam"\n'
            '\t\t"label"\t\t"UserPersistent"\n'
            "\t}\n"
            '\t"1"\n'
            "\t{\n"
            '\t\t"path"\t\t"/steam_shared"\n'
            '\t\t"label"\t\t"SharedReadOnlyLibrary"\n'
            "\t}\n"
            "}\n"
        )
        vdf_path.write_text(content, encoding="utf-8")

    def _sync_shared_library_links(self, user_steamapps: Path) -> None:
        """
        Symlink appmanifest_*.acf and common/<game> from the shared library to point to
        /steam_shared/steamapps/... inside the container while keeping compatdata per-user.
        """
        shared_steamapps = self.shared_steam_dir / "steamapps"
        if not shared_steamapps.exists():
            return

        for manifest in shared_steamapps.glob("appmanifest_*.acf"):
            target_link = user_steamapps / manifest.name
            container_target = f"/steam_shared/steamapps/{manifest.name}"
            if not target_link.exists() and not target_link.is_symlink():
                os.symlink(container_target, target_link)

        shared_common = shared_steamapps / "common"
        user_common = user_steamapps / "common"
        if shared_common.exists():
            for game_dir in shared_common.iterdir():
                if game_dir.is_dir():
                    target_link = user_common / game_dir.name
                    container_target = f"/steam_shared/steamapps/common/{game_dir.name}"
                    if not target_link.exists() and not target_link.is_symlink():
                        os.symlink(container_target, target_link)

                    # Ensure a writable per-user compatdata folder exists for Proton games
                    appid_match = re.search(r"\d+", game_dir.name)
                    if appid_match:
                        (user_steamapps / "compatdata" / appid_match.group(0)).mkdir(
                            parents=True, exist_ok=True
                        )

    def get_user_steam_status(self, user_id: str) -> Dict[str, object]:
        """
        Check whether the user has a remembered Steam login session and persistent saves.
        Never reads or exposes any passwords or secret tokens.
        """
        paths = self.prepare_user_storage(user_id)
        loginusers_vdf = paths.steam_root_dir / "config" / "loginusers.vdf"
        config_vdf = paths.steam_root_dir / "config" / "config.vdf"

        remembered = False
        account_name: Optional[str] = None
        persona_name: Optional[str] = None
        account_hint: Optional[str] = None
        if loginusers_vdf.exists():
            try:
                text = loginusers_vdf.read_text(encoding="utf-8", errors="ignore")
                if '"AccountName"' in text or '"MostRecent"' in text:
                    remembered = True
                    m = re.search(r'"AccountName"\s+"([^"]+)"', text)
                    if m:
                        account_name = m.group(1)
                        account_hint = account_name[:2] + "***" if len(account_name) > 2 else "***"
                    p = re.search(r'"PersonaName"\s+"([^"]+)"', text)
                    if p:
                        persona_name = p.group(1)
            except Exception:
                pass
        elif config_vdf.exists() and config_vdf.stat().st_size > 32:
            remembered = True

        save_data = self.read_cyberarena_save(user_id)
        return {
            "user_id": paths.user_id,
            "steam_login_remembered": remembered,
            "steam_account_name": account_name,
            "steam_persona_name": persona_name,
            "steam_account_hint": account_hint,
            "cyberarena_save": save_data,
        }

    get_user_storage_status = get_user_steam_status

    def read_cyberarena_save(self, user_id: str) -> Dict[str, object]:
        """Read the user's persistent CyberArena 3D save file if present."""
        paths = self.prepare_user_storage(user_id)
        if not paths.cyberarena_save_file.exists():
            return {"high_score": 0, "sessions_played": 0, "exists": False}
        try:
            data = json.loads(paths.cyberarena_save_file.read_text(encoding="utf-8"))
            return {
                "high_score": int(data.get("high_score", 0)),
                "sessions_played": int(data.get("sessions_played", 0)),
                "exists": True,
            }
        except Exception:
            return {"high_score": 0, "sessions_played": 0, "exists": False}

    def list_users(self) -> List[str]:
        self.ensure_base_directories()
        return sorted(
            d.name for d in self.users_root.iterdir() if d.is_dir() and VALID_USER_RE.match(d.name)
        )


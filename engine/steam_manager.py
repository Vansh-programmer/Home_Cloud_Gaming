"""
Steam Library Scanner, VDF Manifest Parser & Isolated App Launcher (Phase 2).

Features:
- Parses Valve's appmanifest_*.acf VDF files from the shared read-only Steam library.
- Generates Steam cover art URLs and game metadata for the Game Library UI.
- Constructs isolated container launch commands for:
  1. Built-in CyberArena 3D (AppID "0") with per-user persistent save files.
  2. Steam GamepadUI / Account Login (AppID "7") where users type Steam passwords
     strictly into Steam's own UI inside the isolated stream.
  3. Any installed Steam game by AppID (steam -gamepadui -applaunch <AppID>).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

KV_PATTERN = re.compile(r'"([^"]+)"\s+"([^"]*)"')


@dataclass
class GameEntry:
    app_id: str
    title: str
    install_dir: str
    size_bytes: int
    cover_url: str
    header_url: str
    category: str  # "builtin" | "steam"
    custom_exec: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def parse_acf_manifest(acf_path: Path) -> Optional[GameEntry]:
    """Parse a Valve Steam appmanifest_<appid>.acf file into a GameEntry."""
    try:
        text = acf_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    kv: Dict[str, str] = {}
    for match in KV_PATTERN.finditer(text):
        key, val = match.group(1), match.group(2)
        if key not in kv:
            kv[key] = val

    app_id = kv.get("appid", "").strip()
    title = kv.get("name", "").strip()
    install_dir = kv.get("installdir", "").strip()
    size_str = kv.get("SizeOnDisk", "0").strip()
    custom_exec = kv.get("CustomExecutable", "").strip() or None

    if not app_id or not title:
        return None

    try:
        size_bytes = int(size_str)
    except ValueError:
        size_bytes = 0

    return GameEntry(
        app_id=app_id,
        title=title,
        install_dir=install_dir,
        size_bytes=size_bytes,
        cover_url=f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_600x900.jpg",
        header_url=f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg",
        category="steam",
        custom_exec=custom_exec,
    )


class SteamLibraryManager:
    """Discovers installed Steam games and builds isolated container launch commands."""

    def __init__(self, shared_steam_dir: Path, extra_steamapps_dirs: Optional[List[Path]] = None) -> None:
        self.shared_steam_dir = shared_steam_dir
        self.extra_steamapps_dirs = extra_steamapps_dirs or []

    def list_games(self, include_builtins: bool = True) -> List[GameEntry]:
        """Return all available games (built-in entries + discovered Steam appmanifests)."""
        games: List[GameEntry] = []
        if include_builtins:
            games.extend(
                [
                    GameEntry(
                        app_id="0",
                        title="CyberArena 3D",
                        install_dir="cyberarena",
                        size_bytes=1048576,
                        cover_url="/assets/cyberarena-cover.svg",
                        header_url="/assets/cyberarena-header.svg",
                        category="builtin",
                    ),
                    GameEntry(
                        app_id="7",
                        title="Steam Big Picture (Account Login & Library)",
                        install_dir="steam",
                        size_bytes=0,
                        cover_url="https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/7/header.jpg",
                        header_url="https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/7/header.jpg",
                        category="steam",
                    ),
                ]
            )

        seen_ids = {"0", "7"}
        search_dirs = [self.shared_steam_dir / "steamapps"] + self.extra_steamapps_dirs

        for steamapps in search_dirs:
            if not steamapps.exists():
                continue
            for acf_file in sorted(steamapps.glob("appmanifest_*.acf")):
                entry = parse_acf_manifest(acf_file)
                if entry and entry.app_id not in seen_ids:
                    # Skip Steamworks Common Redistributables / Proton runtimes
                    lower_title = entry.title.lower()
                    if "proton" in lower_title or "steam linux runtime" in lower_title or entry.app_id == "228980":
                        continue
                    seen_ids.add(entry.app_id)
                    games.append(entry)

        return games

    discover_games = list_games

    def get_game(self, app_id: str) -> Optional[GameEntry]:
        for g in self.list_games():
            if g.app_id == str(app_id):
                return g
        return None

    def build_launch_command(self, app_id: str, inside_container: bool = True) -> List[str]:
        """
        Return the command vector to execute inside the isolated container for a given app_id.
        """
        clean_id = str(app_id).strip()
        project_root = Path("/opt/cloudgaming") if inside_container else Path(__file__).resolve().parent.parent

        if clean_id in ("0", "cyberarena", ""):
            return [str(project_root / "engine" / "test_game" / "arena3d")]

        if clean_id in ("7", "steam", "steam_client"):
            return [
                "/usr/bin/steam",
                "-gamepadui",
                "-nochatui",
                "-nofriendsui",
            ]

        entry = self.get_game(clean_id)
        if entry and entry.custom_exec:
            if inside_container:
                exec_path = f"/steam_shared/steamapps/common/{entry.install_dir}/{entry.custom_exec}"
            else:
                exec_path = str(
                    self.shared_steam_dir / "steamapps" / "common" / entry.install_dir / entry.custom_exec
                )
            return [exec_path]

        if not clean_id.isdigit():
            raise ValueError(f"Unknown or invalid Steam AppID: {app_id}")

        return [
            "/usr/bin/steam",
            "-gamepadui",
            "-applaunch",
            clean_id,
        ]


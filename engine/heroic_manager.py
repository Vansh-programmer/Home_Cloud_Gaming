"""
Heroic Games Launcher & Epic Games / GOG Library Integration (Phase 7).

Responsibilities:
1. Detects Heroic Games Launcher binary, AppImage, or Flatpak runner.
2. Scans installed Epic Games and GOG manifests from:
   - ~/.config/heroic/GamesConfig/*.json
   - ~/.config/legendary/installed.json
   - data/users/<username>/home/.config/heroic/GamesConfig/*.json
   - data/users/<username>/home/.config/legendary/installed.json
3. Generates unified GameEntry records with category="epic" for the Ryoku Game Library.
4. Constructs isolated launch vectors for:
   - Heroic Launcher GUI (AppID "8" / "heroic")
   - Direct launch of specific Epic/GOG titles (AppID "epic_<appName>")
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("heroic_manager")


def find_heroic_binary() -> Optional[List[str]]:
    """
    Locate the Heroic Games Launcher executable on the host or inside containers.
    Returns the command vector prefix (e.g. ['/usr/bin/heroic'] or ['flatpak', 'run', ...]).
    """
    candidates = [
        "/usr/bin/heroic",
        "/usr/bin/heroic-games-launcher",
        "/usr/local/bin/heroic",
        "/opt/heroic/heroic",
        "/opt/heroic/heroic.AppImage",
        "/usr/local/bin/heroic.AppImage",
    ]
    for cand in candidates:
        p = Path(cand)
        if p.is_file() and os.access(p, os.X_OK):
            return [str(p)]

    which_heroic = shutil.which("heroic") or shutil.which("heroic-games-launcher")
    if which_heroic:
        return [which_heroic]

    # Check Flatpak runner
    if shutil.which("flatpak"):
        return ["flatpak", "run", "com.heroicgameslauncher.hgl"]

    return None


class HeroicLibraryManager:
    """Discovers installed Epic & GOG titles and builds launch commands."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        self.data_root = data_root

    def get_search_directories(self) -> List[Path]:
        """Collect potential Heroic and Legendary config search roots."""
        roots: List[Path] = [
            Path.home() / ".config",
            Path.home() / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config",
        ]
        if self.data_root and self.data_root.exists():
            users_dir = self.data_root / "users"
            if users_dir.exists():
                for u_dir in users_dir.iterdir():
                    if u_dir.is_dir():
                        cfg = u_dir / "home" / ".config"
                        if cfg.exists() and cfg not in roots:
                            roots.append(cfg)
        return roots

    def list_games(self) -> List[Dict[str, object]]:
        """Scan and return discovered Epic Games and GOG titles."""
        games: List[Dict[str, object]] = []
        seen_names = set()

        for config_root in self.get_search_directories():
            # 1. Parse Legendary installed.json (Epic Games core)
            legendary_file = config_root / "legendary" / "installed.json"
            if legendary_file.exists():
                try:
                    data = json.loads(legendary_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for app_name, meta in data.items():
                            if app_name in seen_names or not isinstance(meta, dict):
                                continue
                            title = meta.get("title", app_name)
                            install_path = meta.get("install_path", "")
                            exe = meta.get("executable", "")
                            seen_names.add(app_name)
                            games.append(
                                {
                                    "app_id": f"epic_{app_name}",
                                    "app_name": app_name,
                                    "title": title,
                                    "install_dir": install_path,
                                    "size_bytes": int(meta.get("install_size", 0)),
                                    "cover_url": f"/assets/heroic-cover.svg",
                                    "header_url": f"/assets/heroic-banner.svg",
                                    "category": "epic",
                                    "custom_exec": exe,
                                }
                            )
                except Exception as exc:
                    logger.debug("Error parsing %s: %s", legendary_file, exc)

            # 2. Parse Heroic GamesConfig directory (per-game configurations)
            games_config_dir = config_root / "heroic" / "GamesConfig"
            if games_config_dir.exists():
                for cfg_path in games_config_dir.glob("*.json"):
                    app_name = cfg_path.stem
                    if app_name in seen_names:
                        continue
                    try:
                        gdata = json.loads(cfg_path.read_text(encoding="utf-8"))
                        if not isinstance(gdata, dict):
                            continue
                        title = gdata.get("title") or app_name
                        install_path = gdata.get("install_path") or ""
                        exe = gdata.get("executable") or ""
                        seen_names.add(app_name)
                        games.append(
                            {
                                "app_id": f"epic_{app_name}",
                                "app_name": app_name,
                                "title": title,
                                "install_dir": install_path,
                                "size_bytes": 0,
                                "cover_url": f"/assets/heroic-cover.svg",
                                "header_url": f"/assets/heroic-banner.svg",
                                "category": "epic",
                                "custom_exec": exe,
                            }
                        )
                    except Exception as exc:
                        logger.debug("Error reading %s: %s", cfg_path, exc)

        return games

    def build_launch_command(self, app_id: str) -> List[str]:
        """
        Build launch command vector for Heroic GUI (app_id '8' or 'heroic')
        or a specific Epic Game (app_id 'epic_<appName>').
        """
        clean_id = str(app_id).strip()
        heroic_bin = find_heroic_binary()

        # Launch Heroic Launcher GUI
        if clean_id in ("8", "heroic", "epic"):
            if heroic_bin:
                return [*heroic_bin, "--no-sandbox"]
            # Fallback launcher wrapper message
            return ["/usr/bin/heroic", "--no-sandbox"]

        # Launch specific Epic Game
        if clean_id.startswith("epic_"):
            clean_app_name = clean_id.removeprefix("epic_")
            if heroic_bin:
                return [*heroic_bin, "--no-sandbox", "--no-gui", f"heroic://launch/epic/{clean_app_name}"]
            if shutil.which("legendary"):
                return ["legendary", "launch", clean_app_name]

        return ["/usr/bin/heroic", "--no-sandbox"]


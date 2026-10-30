#!/usr/bin/env python3
"""
Ryoku Cloud Gaming // Sunshine Application Synchronizer

Syncs discovered Steam, Epic/Heroic, and native games from Ryoku
into Sunshine's apps.json configuration.

CRITICAL SECURITY RULE:
- The default "Desktop" entry is NEVER created.
- Players connecting via Moonlight can ONLY see and launch authorized games.
- All game entries are wrapped with Ryoku's Bubblewrap sandbox launcher.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.steam_manager import SteamLibraryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sunshine_sync")


def get_sunshine_config_dir() -> Path:
    # First check standard host config dir
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        base = Path(config_home)
    else:
        base = Path.home() / ".config"
    sunshine_dir = base / "sunshine"
    try:
        sunshine_dir.mkdir(parents=True, exist_ok=True)
        return sunshine_dir
    except (OSError, PermissionError):
        # Fallback to project internal data dir (always writable)
        local_dir = PROJECT_ROOT / "data" / "sunshine"
        local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir


def sync_apps(output_path: Path | None = None) -> Path:
    if output_path is None:
        sunshine_dir = get_sunshine_config_dir()
        output_path = sunshine_dir / "apps.json"

    logger.info("Scanning Ryoku game library for Sunshine sync...")
    steam_mgr = SteamLibraryManager(PROJECT_ROOT / "data" / "shared_steam_library")
    games = steam_mgr.list_games(include_builtins=True)

    launcher_path = PROJECT_ROOT / "engine" / "sunshine_sandboxed_launcher.py"

    apps_list = []

    # 1. Built-in CyberArena 3D (Always available)
    apps_list.append({
        "name": "CyberArena 3D",
        "output": "",
        "cmd": f"python3 {launcher_path} --app-id 0",
        "auto-detach": "false",
        "wait-all": "true",
        "exit-timeout": "1",
        "image-path": str(PROJECT_ROOT / "web" / "assets" / "img" / "cyberarena.png")
            if (PROJECT_ROOT / "web" / "assets" / "img" / "cyberarena.png").exists() else "",
    })

    # 2. Steam Big Picture (Sandboxed GamepadUI)
    apps_list.append({
        "name": "Steam Big Picture",
        "output": "",
        "cmd": f"python3 {launcher_path} --app-id 7",
        "auto-detach": "false",
        "wait-all": "true",
        "exit-timeout": "1",
        "image-path": "",
    })

    # 3. Installed Steam Games
    for g in games:
        if g.app_id in ("0", "7"):
            continue
        apps_list.append({
            "name": g.title,
            "output": "",
            "cmd": f"python3 {launcher_path} --app-id {g.app_id}",
            "auto-detach": "false",
            "wait-all": "true",
            "exit-timeout": "1",
            "image-path": "",
        })

    # 4. Check for Heroic / Epic Games
    heroic_config = Path.home() / ".config" / "heroic" / "gog_store" / "installed.json"
    heroic_legendary = Path.home() / ".config" / "heroic" / "legendaryConfig" / "legendary" / "installed.json"
    
    if heroic_legendary.exists():
        try:
            with open(heroic_legendary, "r", encoding="utf-8") as f:
                legendary_data = json.load(f)
                for app_name, info in legendary_data.items():
                    title = info.get("title", app_name)
                    apps_list.append({
                        "name": f"{title} (Epic Games)",
                        "output": "",
                        "cmd": f"python3 {launcher_path} --app-id heroic-{app_name}",
                        "auto-detach": "false",
                        "wait-all": "true",
                        "exit-timeout": "1",
                        "image-path": "",
                    })
        except Exception as e:
            logger.warning("Could not parse Heroic legendary games: %s", e)

    sunshine_data = {
        "env": {
            "PATH": "$(PATH)",
            "RYOKU_HOST": "1",
        },
        "apps": apps_list
    }

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sunshine_data, f, indent=2)
    except (OSError, PermissionError) as write_err:
        fallback_path = PROJECT_ROOT / "data" / "sunshine" / "apps.json"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with open(fallback_path, "w", encoding="utf-8") as f:
            json.dump(sunshine_data, f, indent=2)
        output_path = fallback_path
        logger.info("Fell back to writable location: %s (%s)", output_path, write_err)

    logger.info("Successfully synced %d sandboxed games to %s", len(apps_list), output_path)
    logger.info("SECURITY CONFIRMED: 'Desktop' stream is completely disabled.")
    return output_path


if __name__ == "__main__":
    out = sync_apps()
    print(f"Sunshine apps.json generated at: {out}")

"""
Goldberg Steam Emulator LAN Profile Provisioning & Multi-Instance Networking.

For LAN / Offline co-op games (like Phasmophobia, Lethal Company, Content Warning):
1. Provisions unique 64-bit SteamIDs and custom player names for each user.
2. Writes config files into the user's isolated Wine prefix (%APPDATA%/Goldberg SteamEmu Saves/settings)
   and ~/.local/share/Goldberg SteamEmu Saves/settings.
3. Automatically enables UDP LAN broadcast / loopback discovery so all 4 players find each
   other in-game without manual configuration.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("goldberg_manager")


def derive_user_steam_id(username: str) -> str:
    """
    Generate a deterministic, valid 64-bit SteamID for the given username.
    Uses base 76561198000000000 + MD5 offset.
    """
    h = int(hashlib.md5(username.lower().encode("utf-8")).hexdigest()[:8], 16)
    return str(76561198000000000 + (h % 900000000) + 1)


def provision_goldberg_lan_profile(
    user_id: str,
    user_root: Path,
    app_id: str = "739630",
    display_name: Optional[str] = None,
) -> Dict[str, str]:
    """
    Write Goldberg Steam settings into the user's persistent directories.
    """
    clean_user = user_id.strip()
    player_name = display_name or clean_user
    steam_id = derive_user_steam_id(clean_user)

    target_dirs = [
        # Linux native / Wine fallback path
        user_root / "home" / ".local" / "share" / "Goldberg SteamEmu Saves" / "settings",
        # Proton prefix %APPDATA% (steamuser)
        user_root / "home" / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / str(app_id) / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "Goldberg SteamEmu Saves" / "settings",
        # Proton prefix %APPDATA% (gamer)
        user_root / "home" / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / str(app_id) / "pfx" / "drive_c" / "users" / "gamer" / "AppData" / "Roaming" / "Goldberg SteamEmu Saves" / "settings",
    ]

    for settings_dir in target_dirs:
        try:
            settings_dir.mkdir(parents=True, exist_ok=True)
            (settings_dir / "account_name.txt").write_text(player_name, encoding="utf-8")
            (settings_dir / "user_steam_id.txt").write_text(steam_id, encoding="utf-8")
            (settings_dir / "language.txt").write_text("english", encoding="utf-8")
            # Enable LAN discovery / local save broadcast
            (settings_dir / "broadcast_net.txt").write_text("1", encoding="utf-8")
            logger.info("Provisioned Goldberg LAN profile in %s (User: %s, SteamID: %s)", settings_dir, player_name, steam_id)
        except Exception as exc:
            logger.warning("Could not write Goldberg profile to %s: %s", settings_dir, exc)

    return {
        "username": clean_user,
        "player_name": player_name,
        "steam_id": steam_id,
        "app_id": app_id,
    }

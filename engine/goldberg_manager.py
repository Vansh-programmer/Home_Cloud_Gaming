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
    app_id: str = "1966720",
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
        user_root / "home" / ".local" / "share" / "Goldberg SteamEmu Saves" / str(app_id) / "settings",
    ]

    for aid in {str(app_id), "1966720", "739630"}:
        for username_cand in ("steamuser", "gamer", clean_user):
            base_appdata = user_root / "home" / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / aid / "pfx" / "drive_c" / "users" / username_cand / "AppData" / "Roaming" / "Goldberg SteamEmu Saves"
            target_dirs.append(base_appdata / "settings")
            target_dirs.append(base_appdata / aid / "settings")

    broadcast_content = "127.0.0.1\n255.255.255.255\n"

    for settings_dir in target_dirs:
        try:
            settings_dir.mkdir(parents=True, exist_ok=True)
            (settings_dir / "account_name.txt").write_text(player_name, encoding="utf-8")
            (settings_dir / "user_steam_id.txt").write_text(steam_id, encoding="utf-8")
            (settings_dir / "language.txt").write_text("english", encoding="utf-8")
            (settings_dir / "broadcast_net.txt").write_text("1", encoding="utf-8")
            (settings_dir / "custom_broadcasts.txt").write_text(broadcast_content, encoding="utf-8")
            logger.debug("Provisioned Goldberg LAN profile in %s (User: %s, SteamID: %s)", settings_dir, player_name, steam_id)
        except Exception as exc:
            logger.warning("Could not write Goldberg profile to %s: %s", settings_dir, exc)

    return {
        "username": clean_user,
        "player_name": player_name,
        "steam_id": steam_id,
        "app_id": app_id,
    }


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

import json
import os
import re
import shlex
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

KV_PATTERN = re.compile(r'"([^"]+)"\s+"([^"]*)"')

DEFAULT_ONLINEFIX_DLL_OVERRIDES = (
    "OnlineFix64=n;OnlineFix=n;SteamOverlay64=n;SteamOverlay=n;winmm=n,b;dnet=n;steam_api64=n;steam_api=n;PhotonBridge=n;version=n,b"
)


def parse_launch_options(
    launch_options: Optional[str],
    base_cmd: List[str],
    base_env: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], Dict[str, str]]:
    """
    Parse a Steam launch options string like:
    WINEDLLOVERRIDES="OnlineFix64=n;steam_api64=n" gamemoderun %command% -force-d3d11

    Extracts:
    1. Environment variables (KEY=VAL) -> injected into env dict.
    2. Command wrappers (e.g. gamemoderun, mangohud) -> prepended to base_cmd.
    3. Arguments after %command% -> appended to base_cmd.
    """
    env = dict(base_env or {})
    if not launch_options or not launch_options.strip():
        return list(base_cmd), env

    tokens = shlex.split(launch_options.strip())
    if "%command%" in tokens:
        idx = tokens.index("%command%")
        before = tokens[:idx]
        after = tokens[idx + 1 :]
    else:
        before = []
        after = tokens

    cmd_prefix: List[str] = []
    for tok in before:
        if "=" in tok and not tok.startswith("-"):
            k, v = tok.split("=", 1)
            env[k.strip()] = v.strip()
        else:
            cmd_prefix.append(tok)

    cmd_suffix: List[str] = []
    for tok in after:
        if "=" in tok and not tok.startswith("-") and not before:
            k, v = tok.split("=", 1)
            env[k.strip()] = v.strip()
        else:
            cmd_suffix.append(tok)

    return [*cmd_prefix, *base_cmd, *cmd_suffix], env


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
    launch_options: Optional[str] = None

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
                        cover_url="/assets/steam-cover.svg",
                        header_url="/assets/steam-cover.svg",
                        category="steam",
                    ),
                    GameEntry(
                        app_id="739630",
                        title="Phasmophobia (Co-op 4P LAN)",
                        install_dir="Phasmophobia",
                        size_bytes=18253611008,
                        cover_url="https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/739630/library_600x900.jpg",
                        header_url="https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/739630/header.jpg",
                        category="steam",
                        custom_exec="Phasmophobia.exe",
                        launch_options=f'WINEDLLOVERRIDES="{DEFAULT_ONLINEFIX_DLL_OVERRIDES}" %command%',
                    ),
                ]
            )

        seen_ids = {"0", "7", "739630"}
        search_dirs = [self.shared_steam_dir / "steamapps"] + self.extra_steamapps_dirs

        try:
            from engine.host_library import collect_host_mounts, host_library_enabled, host_manifest_dir
            if host_library_enabled():
                # Prepare sanitized manifests and include in discovery search
                collect_host_mounts(self.shared_steam_dir.parent)
                h_dir = host_manifest_dir(self.shared_steam_dir.parent)
                if h_dir.exists() and h_dir not in search_dirs:
                    search_dirs.append(h_dir)
        except Exception:
            pass

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

    @property
    def launch_options_file(self) -> Path:
        return self.shared_steam_dir.parent / "game_launch_options.json"

    def get_custom_launch_options(self, app_id: str) -> Optional[str]:
        clean_id = str(app_id).strip()
        if self.launch_options_file.exists():
            try:
                data = json.loads(self.launch_options_file.read_text(encoding="utf-8"))
                if clean_id in data and data[clean_id]:
                    return str(data[clean_id])
            except Exception:
                pass
        entry = self.get_game(clean_id)
        if entry and entry.launch_options:
            return entry.launch_options
        if clean_id == "739630":
            return f'WINEDLLOVERRIDES="{DEFAULT_ONLINEFIX_DLL_OVERRIDES}" %command%'
        return None

    def set_custom_launch_options(self, app_id: str, options: str) -> None:
        clean_id = str(app_id).strip()
        data = {}
        if self.launch_options_file.exists():
            try:
                data = json.loads(self.launch_options_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[clean_id] = options.strip()
        self.launch_options_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
            common_base = Path("/steam_shared/steamapps/common") if inside_container else (self.shared_steam_dir / "steamapps" / "common")
            game_folder = common_base / entry.install_dir
            exec_name = entry.custom_exec

            # Auto-detect OnlineFix launcher if present
            if game_folder.exists():
                for candidate in ("Launcher.exe", "Phasmophobia_Launcher.exe", "Photon Launcher.exe", entry.custom_exec):
                    if candidate and (game_folder / candidate).exists():
                        exec_name = candidate
                        break

            if inside_container:
                exec_path = f"/steam_shared/steamapps/common/{entry.install_dir}/{exec_name}"
            else:
                exec_path = str(game_folder / exec_name)

            if exec_path.lower().endswith(".exe"):
                # Search for Proton runtime or Wine
                proton_bin = None
                if common_base.exists():
                    for p in sorted(common_base.glob("Proton*"), reverse=True):
                        cand = p / "proton"
                        if cand.exists():
                            proton_bin = cand
                            break
                if proton_bin:
                    return [str(proton_bin), "run", exec_path]
                if shutil.which("wine"):
                    return ["wine", exec_path]
                if Path("/usr/bin/steam").exists():
                    return ["/usr/bin/steam", "-gamepadui", "-applaunch", clean_id]
            return [exec_path]

        if not clean_id.isdigit():
            raise ValueError(f"Unknown or invalid Steam AppID: {app_id}")

        extra_args: List[str] = []
        # Bypass third-party pre-launchers that block headless streaming
        if clean_id in ("1091500", "292030"):  # Cyberpunk 2077, The Witcher 3 (REDlauncher)
            extra_args = ["--launcher-skip"]
        elif clean_id in ("1086940",):  # Baldur's Gate 3 (Larian Launcher)
            extra_args = ["--skip-launcher"]

        return [
            "/usr/bin/steam",
            "-gamepadui",
            "-applaunch",
            clean_id,
            *extra_args,
        ]


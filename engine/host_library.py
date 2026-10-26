"""
Host Steam library pass-through (zero duplication, read-only).

Lets the games you already installed with Steam on THIS PC show up in the cloud library
WITHOUT copying a single game file and WITHOUT giving cloud sessions access to the PC.

What is exposed to a cloud session (read-only bind mounts, nothing else):
  * <library>/steamapps/common/<installdir>        -> /steam_shared/steamapps/common/<installdir>
  * a SANITIZED copy of <library>/steamapps/appmanifest_<id>.acf
                                                   -> /steam_shared/steamapps/appmanifest_<id>.acf

What is NEVER exposed: the host home directory, compatdata (host Proton prefixes / saves),
shadercache, downloading, workshop, userdata, Steam login tokens, other libraries' files, or any
path that does not resolve inside <library>/steamapps/common.

Configuration (environment / .env):
    HOST_STEAM_LIBRARY = off          (default: feature disabled)
                       = auto         (read host Steam's libraryfolders.vdf)
                       = /path/a:/path/b   (explicit Steam library roots containing steamapps/)
    HOST_STEAM_APPIDS  = 1245620,730  (optional allow-list; empty = every installed game)
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

KV_PATTERN = re.compile(r'"([^"]+)"\s+"([^"]*)"')
# Manifest fields that identify the host account / activity; blanked in the shared copy.
SANITIZE_PATTERN = re.compile(
    r'("(?:LastOwner|LastPlayed|LastUpdated|BytesToDownload|BytesDownloaded|BytesToStage|BytesStaged)"\s+")[^"]*(")'
)
# Runtimes cloud sessions need (Proton etc. live in steamapps/common too) - always mounted
SAFE_INSTALL_DIR = re.compile(r"^[^/\\\x00]+$")


@dataclass(frozen=True)
class LibraryMount:
    """One read-only bind mount: host `src` -> container `dst`."""

    src: Path
    dst: str


def host_library_setting() -> str:
    return os.environ.get("HOST_STEAM_LIBRARY", "off").strip()


def host_library_enabled() -> bool:
    return host_library_setting().lower() not in ("", "off", "0", "false", "no")


def _parse_libraryfolders(vdf: Path) -> List[Path]:
    roots: List[Path] = []
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return roots
    for key, val in KV_PATTERN.findall(text):
        if key == "path" and val:
            roots.append(Path(val))
    return roots


def discover_library_roots() -> List[Path]:
    """Return Steam library roots (directories that contain `steamapps/`) per configuration."""
    setting = host_library_setting()
    if not host_library_enabled():
        return []

    candidates: List[Path] = []
    if setting.lower() == "auto":
        home = Path(os.environ.get("HOST_STEAM_HOME", str(Path.home())))
        steam_homes = [
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        ]
        for steam_home in steam_homes:
            if not steam_home.exists():
                continue
            candidates.append(steam_home)
            for vdf in (
                steam_home / "config" / "libraryfolders.vdf",
                steam_home / "steamapps" / "libraryfolders.vdf",
            ):
                candidates.extend(_parse_libraryfolders(vdf))
    else:
        for part in setting.split(":"):
            part = part.strip()
            if part:
                candidates.append(Path(part))

    roots: List[Path] = []
    seen: Set[Path] = set()
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        # Accept either the root that contains steamapps/ or the steamapps/ dir itself
        if resolved.name == "steamapps":
            resolved = resolved.parent
        if (resolved / "steamapps").is_dir():
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _allowed_app_ids() -> Optional[Set[str]]:
    raw = os.environ.get("HOST_STEAM_APPIDS", "").strip()
    if not raw:
        return None
    return {p.strip() for p in re.split(r"[,\s]+", raw) if p.strip().isdigit()}


def sanitize_manifest_text(text: str) -> str:
    return SANITIZE_PATTERN.sub(lambda m: f"{m.group(1)}0{m.group(2)}", text)


def collect_host_mounts(data_root: Path) -> List[LibraryMount]:
    """
    Build the read-only mount list for every installed game in the configured host libraries.
    Writes sanitized manifest copies to `<data_root>/host_manifests/` (never the originals).
    """
    mounts: List[LibraryMount] = []
    if not host_library_enabled():
        return mounts

    out_dir = data_root / "host_manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    allowed = _allowed_app_ids()
    used_app_ids: Set[str] = set()
    used_dirs: Set[str] = set()
    kept_files: Set[str] = set()

    for root in discover_library_roots():
        steamapps = root / "steamapps"
        common = steamapps / "common"
        for acf in sorted(steamapps.glob("appmanifest_*.acf")):
            m = re.fullmatch(r"appmanifest_(\d+)\.acf", acf.name)
            if not m:
                continue
            app_id = m.group(1)
            if app_id in used_app_ids:
                continue
            if allowed is not None and app_id not in allowed:
                continue
            try:
                text = acf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            kv: Dict[str, str] = {}
            for k, v in KV_PATTERN.findall(text):
                kv.setdefault(k, v)
            install_dir = kv.get("installdir", "").strip()
            if not install_dir or not SAFE_INSTALL_DIR.match(install_dir) or install_dir in (".", ".."):
                continue

            game_src = (common / install_dir)
            try:
                game_real = game_src.resolve()
                common_real = common.resolve()
            except OSError:
                continue
            # Must really be a directory inside <library>/steamapps/common (no symlink escapes)
            if not game_real.is_dir() or common_real not in game_real.parents:
                continue
            if install_dir in used_dirs:
                continue

            safe_manifest = out_dir / acf.name
            safe_manifest.write_text(sanitize_manifest_text(text), encoding="utf-8")
            os.chmod(safe_manifest, 0o644)
            kept_files.add(acf.name)

            used_app_ids.add(app_id)
            used_dirs.add(install_dir)
            mounts.append(
                LibraryMount(safe_manifest, f"/steam_shared/steamapps/{acf.name}")
            )
            mounts.append(
                LibraryMount(game_real, f"/steam_shared/steamapps/common/{install_dir}")
            )

    # Drop stale sanitized manifests for games that were uninstalled on the host
    for stale in out_dir.glob("appmanifest_*.acf"):
        if stale.name not in kept_files:
            try:
                stale.unlink()
            except OSError:
                pass
    return mounts


def host_manifest_dir(data_root: Path) -> Path:
    """Directory of sanitized manifests, laid out like a `steamapps/` folder for scanning."""
    return data_root / "host_manifests"


def describe_status(data_root: Path) -> Dict[str, object]:
    """Small status dict for the admin API / CLI."""
    mounts = collect_host_mounts(data_root) if host_library_enabled() else []
    games = [m for m in mounts if "/common/" in m.dst]
    return {
        "enabled": host_library_enabled(),
        "setting": host_library_setting(),
        "library_roots": [str(r) for r in discover_library_roots()],
        "shared_game_count": len(games),
        "allowlist": sorted(_allowed_app_ids() or []),
    }


__all__ = [
    "LibraryMount",
    "collect_host_mounts",
    "describe_status",
    "discover_library_roots",
    "host_library_enabled",
    "host_manifest_dir",
    "sanitize_manifest_text",
]


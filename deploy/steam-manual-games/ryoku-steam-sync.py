#!/usr/bin/env python3
"""
Ryoku Cloud Gaming — Automatic Manual Game Importer for Steam.

Scans /shared_games (mounted :ro) and:
1. Mirrors each manual game directory into $HOME/.local/share/ryoku-games/<GameName>
   using real writable directories and read-only asset symlinks (preserving :ro on
   /shared_games while allowing games to write saves/configs/logs next to their .exe).
2. Links any /shared_games/steamapps/common/* and appmanifest_*.acf into the user's
   writable Steam library ($HOME/.local/share/Steam/steamapps).
3. Registers all discovered standalone games (.exe, .AppImage, .x86_64, .sh) into
   Steam's binary shortcuts.vdf for every Steam user profile in userdata/.
4. Automatically enables Proton (proton_experimental) in Steam's config.vdf
   CompatToolMapping for Windows .exe games.
"""

from __future__ import annotations

import binascii
import json
import os
import re
import shutil
import struct
import sys
import time
from pathlib import Path

SHARED_GAMES_DIR = Path(os.environ.get("RYOKU_SHARED_GAMES", "/shared_games"))
HOME_DIR = Path(os.environ.get("HOME", "/home/retro"))
USER_GAMES_DIR = HOME_DIR / ".local" / "share" / "ryoku-games"

STEAM_DIRS = [
    HOME_DIR / ".local" / "share" / "Steam",
    HOME_DIR / ".steam" / "steam",
    HOME_DIR / ".steam" / "debian-installation",
]

IGNORE_EXE_PATTERNS = (
    "unins",
    "vc_redist",
    "vcredist",
    "dxsetup",
    "directx",
    "dotnet",
    "crashpad",
    "crashhandler",
    "crashreport",
    "unitycrashhandler",
    "ue4prereq",
    "ueprereq",
    "easyanticheat",
    "battleye",
    "crs-handler",
    "cephtmlengine",
    "notification_helper",
    "steamerrorreporter",
)

WRITABLE_CONFIG_EXTS = {
    ".ini",
    ".cfg",
    ".conf",
    ".json",
    ".xml",
    ".txt",
    ".sav",
    ".save",
    ".dat",
    ".log",
}


def log(msg: str) -> None:
    print(f"[ryoku-steam-sync] {msg}", flush=True)


def get_steam_root() -> Path:
    for candidate in STEAM_DIRS:
        if candidate.exists():
            return candidate
    default_root = HOME_DIR / ".local" / "share" / "Steam"
    default_root.mkdir(parents=True, exist_ok=True)
    return default_root


def mirror_game_to_writable_overlay(src_dir: Path, dst_dir: Path) -> None:
    """
    Create real writable directories in dst_dir and symlink read-only asset files
    from src_dir. Small config/save files (< 1 MiB) are copied once so games can
    modify them in-place without writing to /shared_games (:ro).
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        rel = Path(root).relative_to(src_dir)
        target_root = dst_dir / rel
        target_root.mkdir(parents=True, exist_ok=True)

        for d in dirs:
            (target_root / d).mkdir(exist_ok=True)

        for f in files:
            src_file = Path(root) / f
            dst_file = target_root / f
            ext = src_file.suffix.lower()
            try:
                is_small_cfg = ext in WRITABLE_CONFIG_EXTS and src_file.stat().st_size < 1024 * 1024
            except OSError:
                is_small_cfg = False

            if is_small_cfg:
                if not dst_file.exists() and not dst_file.is_symlink():
                    try:
                        shutil.copy2(src_file, dst_file)
                        dst_file.chmod(0o664)
                    except OSError:
                        pass
            else:
                if dst_file.is_symlink():
                    try:
                        if dst_file.resolve() == src_file.resolve():
                            continue
                    except OSError:
                        pass
                    dst_file.unlink(missing_ok=True)
                elif dst_file.exists():
                    continue
                try:
                    dst_file.symlink_to(src_file)
                except OSError:
                    pass


def find_best_executable(game_dir: Path) -> Path | None:
    """Find the primary game executable (.exe, .AppImage, .x86_64, or .sh) in game_dir."""
    meta_file = game_dir / "ryoku-game.json"
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if "exe" in meta:
                custom_exe = game_dir / meta["exe"]
                if custom_exe.is_file():
                    return custom_exe
        except Exception:
            pass

    candidates: list[tuple[int, int, Path]] = []
    folder_slug = re.sub(r"[^a-z0-9]", "", game_dir.name.lower())

    for root, _dirs, files in os.walk(game_dir):
        rel_depth = len(Path(root).relative_to(game_dir).parts)
        if rel_depth > 4:
            continue
        for fname in files:
            fpath = Path(root) / fname
            lower = fname.lower()
            if any(pat in lower for pat in IGNORE_EXE_PATTERNS):
                continue

            ext = fpath.suffix.lower()
            is_linux_bin = ext in (".appimage", ".x86_64", ".sh")
            is_win_exe = ext == ".exe"
            if not (is_win_exe or is_linux_bin):
                continue

            try:
                size = fpath.stat().st_size
            except OSError:
                size = 0

            name_slug = re.sub(r"[^a-z0-9]", "", fpath.stem.lower())
            score = 0
            if folder_slug and (folder_slug in name_slug or name_slug in folder_slug):
                score += 100
            if rel_depth == 0:
                score += 40
            elif rel_depth == 1:
                score += 20
            if is_linux_bin:
                score += 15
            candidates.append((score, size, fpath))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def sync_steamapps_library(steam_root: Path) -> None:
    """Link /shared_games/steamapps into the user's writable Steam library."""
    shared_steamapps = SHARED_GAMES_DIR / "steamapps"
    if not shared_steamapps.is_dir():
        return

    user_steamapps = steam_root / "steamapps"
    user_common = user_steamapps / "common"
    user_common.mkdir(parents=True, exist_ok=True)

    shared_common = shared_steamapps / "common"
    if shared_common.is_dir():
        for game_folder in shared_common.iterdir():
            if not game_folder.is_dir():
                continue
            target = user_common / game_folder.name
            if not target.exists() and not target.is_symlink():
                try:
                    target.symlink_to(game_folder)
                    log(f"Linked Steam common folder: {game_folder.name}")
                except OSError:
                    pass

    for acf in shared_steamapps.glob("appmanifest_*.acf"):
        target_acf = user_steamapps / acf.name
        if not target_acf.exists():
            try:
                shutil.copy2(acf, target_acf)
                target_acf.chmod(0o664)
                log(f"Copied Steam manifest: {acf.name}")
            except OSError:
                pass


def compute_shortcut_appid(exe_quoted: str, app_name: str) -> int:
    crc = binascii.crc32((exe_quoted + app_name).encode("utf-8")) & 0xFFFFFFFF
    return crc | 0x80000000


def parse_shortcuts_vdf(data: bytes) -> list[dict[str, object]]:
    """Parse existing binary shortcuts.vdf entries so user-created shortcuts are preserved."""
    entries: list[dict[str, object]] = []
    idx = 0
    n = len(data)

    def read_cstring(pos: int) -> tuple[str, int]:
        end = data.find(b"\x00", pos)
        if end == -1:
            return "", n
        return data[pos:end].decode("utf-8", errors="replace"), end + 1

    if n < 12 or data[0] != 0x00:
        return entries
    top_key, idx = read_cstring(1)
    if top_key.lower() != "shortcuts":
        return entries

    while idx < n:
        t = data[idx]
        idx += 1
        if t == 0x08:
            break
        if t != 0x00:
            break
        _entry_idx_str, idx = read_cstring(idx)
        entry: dict[str, object] = {}
        while idx < n:
            ft = data[idx]
            idx += 1
            if ft == 0x08:
                break
            fkey, idx = read_cstring(idx)
            if ft == 0x01:
                fval_s, idx = read_cstring(idx)
                entry[fkey] = fval_s
            elif ft == 0x02:
                if idx + 4 > n:
                    break
                fval_i = struct.unpack("<I", data[idx : idx + 4])[0]
                idx += 4
                entry[fkey] = fval_i
            elif ft == 0x00:
                tags: list[str] = []
                while idx < n:
                    tt = data[idx]
                    idx += 1
                    if tt == 0x08:
                        break
                    _tkey, idx = read_cstring(idx)
                    if tt == 0x01:
                        tval, idx = read_cstring(idx)
                        tags.append(tval)
                    elif tt == 0x02:
                        idx += 4
                entry[fkey] = tags
        if entry:
            entries.append(entry)
    return entries


def build_shortcuts_vdf(entries: list[dict[str, object]]) -> bytes:
    """Serialize shortcuts list into Valve's binary shortcuts.vdf format."""
    buf = bytearray()
    buf.append(0x00)
    buf.extend(b"shortcuts\x00")

    for i, entry in enumerate(entries):
        buf.append(0x00)
        buf.extend(f"{i}\x00".encode("utf-8"))

        def put_u32(key: str, val: int) -> None:
            buf.append(0x02)
            buf.extend(key.encode("utf-8") + b"\x00")
            buf.extend(struct.pack("<I", int(val) & 0xFFFFFFFF))

        def put_str(key: str, val: str) -> None:
            buf.append(0x01)
            buf.extend(key.encode("utf-8") + b"\x00")
            buf.extend(str(val).encode("utf-8") + b"\x00")

        put_u32("appid", int(entry.get("appid", 0)))
        put_str("AppName", str(entry.get("AppName", "")))
        put_str("Exe", str(entry.get("Exe", "")))
        put_str("StartDir", str(entry.get("StartDir", "")))
        put_str("icon", str(entry.get("icon", "")))
        put_str("ShortcutPath", str(entry.get("ShortcutPath", "")))
        put_str("LaunchOptions", str(entry.get("LaunchOptions", "")))
        put_u32("IsHidden", int(entry.get("IsHidden", 0)))
        put_u32("AllowDesktopConfig", int(entry.get("AllowDesktopConfig", 1)))
        put_u32("AllowOverlay", int(entry.get("AllowOverlay", 1)))
        put_u32("OpenVR", int(entry.get("OpenVR", 0)))
        put_u32("Devkit", int(entry.get("Devkit", 0)))
        put_str("DevkitGameID", str(entry.get("DevkitGameID", "")))
        put_u32("DevkitOverrideAppID", int(entry.get("DevkitOverrideAppID", 0)))
        put_u32("LastPlayTime", int(entry.get("LastPlayTime", 0)))
        put_str("FlatpakAppID", str(entry.get("FlatpakAppID", "")))

        buf.append(0x00)
        buf.extend(b"tags\x00")
        tags = entry.get("tags", ["Ryoku Manual"])
        if isinstance(tags, list):
            for tidx, tag in enumerate(tags):
                put_str(str(tidx), str(tag))
        buf.append(0x08)

        buf.append(0x08)

    buf.append(0x08)
    buf.append(0x08)
    return bytes(buf)


def ensure_proton_compat_mapping(steam_root: Path, proton_appids: list[int]) -> None:
    """Ensure Windows .exe shortcuts have proton_experimental enabled in config.vdf."""
    if not proton_appids:
        return
    config_dir = steam_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_vdf = config_dir / "config.vdf"

    mapping_blocks = []
    for appid in proton_appids:
        unsigned_key = str(appid & 0xFFFFFFFF)
        signed_key = str((appid & 0xFFFFFFFF) - 0x100000000)
        for key in (unsigned_key, signed_key):
            mapping_blocks.append(
                f'\t\t\t\t\t"{key}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}}'
            )

    if not config_vdf.exists():
        content = (
            '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
            '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
            + "\n".join(mapping_blocks)
            + "\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n"
        )
        config_vdf.write_text(content, encoding="utf-8")
        return

    try:
        text = config_vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    new_blocks = []
    for appid in proton_appids:
        unsigned_key = str(appid & 0xFFFFFFFF)
        if f'"{unsigned_key}"' not in text:
            new_blocks.append(
                f'\t\t\t\t\t"{unsigned_key}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}}'
            )

    if not new_blocks:
        return

    if '"CompatToolMapping"' in text:
        idx = text.find('"CompatToolMapping"')
        brace_idx = text.find("{", idx)
        if brace_idx != -1:
            updated = text[: brace_idx + 1] + "\n" + "\n".join(new_blocks) + text[brace_idx + 1 :]
            config_vdf.write_text(updated, encoding="utf-8")
    elif '"Steam"' in text:
        idx = text.find('"Steam"')
        brace_idx = text.find("{", idx)
        if brace_idx != -1:
            block = '\n\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n' + "\n".join(new_blocks) + "\n\t\t\t\t}"
            updated = text[: brace_idx + 1] + block + text[brace_idx + 1 :]
            config_vdf.write_text(updated, encoding="utf-8")


def discover_manual_games() -> list[dict[str, object]]:
    """Scan /shared_games for standalone game folders and mirror them into USER_GAMES_DIR."""
    discovered: list[dict[str, object]] = []
    if not SHARED_GAMES_DIR.is_dir():
        return discovered

    search_roots = [SHARED_GAMES_DIR]
    manual_subdir = SHARED_GAMES_DIR / "manual"
    if manual_subdir.is_dir():
        search_roots.append(manual_subdir)

    seen_dirs: set[Path] = set()
    for root in search_roots:
        for item in sorted(root.iterdir()):
            if not item.is_dir():
                continue
            if item.name in ("steamapps", "manual", ".git") or item.name.startswith("."):
                continue
            resolved = item.resolve()
            if resolved in seen_dirs:
                continue
            seen_dirs.add(resolved)

            best_exe = find_best_executable(item)
            if not best_exe:
                continue

            writable_game_dir = USER_GAMES_DIR / item.name
            mirror_game_to_writable_overlay(item, writable_game_dir)

            rel_exe = best_exe.relative_to(item)
            target_exe = writable_game_dir / rel_exe
            try:
                if not target_exe.is_symlink():
                    target_exe.chmod(0o755)
            except OSError:
                pass

            app_name = item.name.replace("_", " ").strip()
            launch_options = ""
            meta_file = item / "ryoku-game.json"
            if meta_file.is_file():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    app_name = str(meta.get("title") or app_name)
                    launch_options = str(meta.get("launch_options") or "")
                except Exception:
                    pass

            exe_quoted = f'"{target_exe}"'
            start_dir_quoted = f'"{target_exe.parent}"'
            appid = compute_shortcut_appid(exe_quoted, app_name)
            is_windows_exe = target_exe.suffix.lower() == ".exe"

            discovered.append(
                {
                    "appid": appid,
                    "AppName": app_name,
                    "Exe": exe_quoted,
                    "StartDir": start_dir_quoted,
                    "icon": "",
                    "ShortcutPath": "",
                    "LaunchOptions": launch_options,
                    "IsHidden": 0,
                    "AllowDesktopConfig": 1,
                    "AllowOverlay": 1,
                    "OpenVR": 0,
                    "Devkit": 0,
                    "DevkitGameID": "",
                    "DevkitOverrideAppID": 0,
                    "LastPlayTime": 0,
                    "FlatpakAppID": "",
                    "tags": ["Ryoku Manual"],
                    "is_windows_exe": is_windows_exe,
                }
            )
    return discovered


def sync_all() -> int:
    steam_root = get_steam_root()
    sync_steamapps_library(steam_root)
    discovered = discover_manual_games()
    if not discovered:
        return 0

    userdata_root = steam_root / "userdata"
    userdata_root.mkdir(parents=True, exist_ok=True)
    user_dirs = [d for d in userdata_root.iterdir() if d.is_dir() and d.name.isdigit()]
    if not user_dirs:
        default_user = userdata_root / "0"
        default_user.mkdir(parents=True, exist_ok=True)
        user_dirs = [default_user]

    proton_appids = [int(g["appid"]) for g in discovered if g.get("is_windows_exe")]

    for udir in user_dirs:
        cfg_dir = udir / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        shortcuts_path = cfg_dir / "shortcuts.vdf"

        existing: list[dict[str, object]] = []
        if shortcuts_path.is_file():
            try:
                existing = parse_shortcuts_vdf(shortcuts_path.read_bytes())
            except Exception:
                existing = []

        by_exe = {str(entry.get("Exe", "")): entry for entry in existing}
        changed = False
        for game in discovered:
            exe_key = str(game["Exe"])
            if exe_key not in by_exe:
                existing.append(game)
                by_exe[exe_key] = game
                changed = True
                log(f"Registered manual game in Steam ({udir.name}): {game['AppName']} -> {game['Exe']}")

        if changed or not shortcuts_path.is_file():
            shortcuts_path.write_bytes(build_shortcuts_vdf(existing))

    ensure_proton_compat_mapping(steam_root, proton_appids)
    return len(discovered)


def main() -> None:
    if "--list" in sys.argv:
        games = discover_manual_games()
        if not games:
            print("No manual games found in /shared_games.")
            return
        for g in games:
            kind = "Proton (.exe)" if g["is_windows_exe"] else "Native Linux"
            print(f"- {g['AppName']} [{kind}] -> {g['Exe']}")
        return

    count = sync_all()
    log(f"Initial manual game sync complete ({count} standalone game(s) synced).")

    if "--watch" in sys.argv:
        # Watch for newly signed-in Steam accounts or newly dropped folders in /shared_games
        seen_uids: set[str] = set()
        seen_items: set[str] = set()
        if SHARED_GAMES_DIR.is_dir():
            seen_items = {p.name for p in SHARED_GAMES_DIR.iterdir() if p.is_dir()}
        while True:
            time.sleep(5)
            try:
                steam_root = get_steam_root()
                userdata_root = steam_root / "userdata"
                current_uids: set[str] = set()
                if userdata_root.is_dir():
                    current_uids = {d.name for d in userdata_root.iterdir() if d.is_dir() and d.name.isdigit()}
                current_items: set[str] = set()
                if SHARED_GAMES_DIR.is_dir():
                    current_items = {p.name for p in SHARED_GAMES_DIR.iterdir() if p.is_dir()}
                if (current_uids - seen_uids) or (current_items != seen_items):
                    seen_uids = current_uids
                    seen_items = current_items
                    sync_all()
            except Exception:
                pass


if __name__ == "__main__":
    main()


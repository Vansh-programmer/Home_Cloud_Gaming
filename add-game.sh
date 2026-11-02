#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="${REPO_DIR}/data/shared_games"
SYNC_SCRIPT="${REPO_DIR}/deploy/steam-manual-games/ryoku-steam-sync.py"

mkdir -p "${SHARED_DIR}"

usage() {
  cat << 'EOF'
========================================================================
  RYOKU CLOUD GAMING // MANUAL STEAM GAME MANAGER
========================================================================
Usage:
  ./add-game.sh list
      List all manual games currently in data/shared_games/ and show
      their detected executable (Proton .exe or Native Linux).

  ./add-game.sh add <path-to-game-folder-or-archive> [Custom Game Title]
      Copy or extract a manually downloaded game folder (.zip, .tar.gz,
      .7z, .AppImage, or directory) into data/shared_games/ so Steam
      automatically imports it as a ready-to-play game with Proton.

  ./add-game.sh sync
      Trigger an immediate sync inside any running Steam container.

Directory Layout Supported in data/shared_games/:
  1. Standalone / Repack / Portable Games (Windows .exe or Linux):
     data/shared_games/<Game Title>/<Game>.exe
  2. Official Steam Library Backups:
     data/shared_games/steamapps/appmanifest_<appid>.acf
     data/shared_games/steamapps/common/<Game Folder>/
========================================================================
EOF
}

list_games() {
  echo "========================================================================"
  echo "  MANUAL GAMES IN: ${SHARED_DIR}"
  echo "========================================================================"
  RYOKU_SHARED_GAMES="${SHARED_DIR}" HOME="/tmp/ryoku-preview" python3 "${SYNC_SCRIPT}" --list
  rm -rf /tmp/ryoku-preview
}

sync_running_steam() {
  local cid
  cid="$(docker ps --filter "ancestor=ghcr.io/games-on-whales/steam:edge" --format '{{.ID}}' | head -n 1 || true)"
  if [ -n "${cid}" ]; then
    echo "[INFO] Syncing manual games into active Steam container (${cid})..."
    docker exec -u retro "${cid}" /usr/bin/python3 /opt/gow/ryoku-steam-sync.py || true
  else
    echo "[OK] Game staged in data/shared_games/. It will auto-import into Steam on next launch."
  fi
}

cmd="${1:-help}"
case "${cmd}" in
  list|ls)
    list_games
    ;;
  sync)
    sync_running_steam
    ;;
  add)
    src="${2:-}"
    custom_name="${3:-}"
    if [ -z "${src}" ] || [ ! -e "${src}" ]; then
      echo "[ERROR] Please provide a valid path to a downloaded game folder or archive." >&2
      usage
      exit 1
    fi
    base="$(basename "${src}")"
    game_name="${custom_name:-${base%.*}}"
    target_dir="${SHARED_DIR}/${game_name}"

    if [ -d "${src}" ]; then
      echo "[INFO] Copying game directory to ${target_dir}..."
      mkdir -p "${target_dir}"
      cp -a "${src}/." "${target_dir}/"
    elif [[ "${src}" == *.zip ]]; then
      echo "[INFO] Extracting ZIP archive to ${target_dir}..."
      mkdir -p "${target_dir}"
      unzip -q -o "${src}" -d "${target_dir}"
    elif [[ "${src}" == *.tar.gz || "${src}" == *.tgz || "${src}" == *.tar.xz || "${src}" == *.tar ]]; then
      echo "[INFO] Extracting TAR archive to ${target_dir}..."
      mkdir -p "${target_dir}"
      tar -xf "${src}" -C "${target_dir}"
    elif [[ "${src}" == *.7z ]]; then
      echo "[INFO] Extracting 7z archive to ${target_dir}..."
      mkdir -p "${target_dir}"
      7z x "${src}" -o"${target_dir}" -y >/dev/null
    elif [[ "${src}" == *.AppImage || "${src}" == *.exe || "${src}" == *.sh || "${src}" == *.x86_64 ]]; then
      echo "[INFO] Installing standalone executable to ${target_dir}..."
      mkdir -p "${target_dir}"
      cp -a "${src}" "${target_dir}/"
      chmod +x "${target_dir}/$(basename "${src}")"
    else
      echo "[ERROR] Unsupported file format: ${src}" >&2
      exit 1
    fi

    chmod -R a+rX "${target_dir}"
    echo "[OK] Installed '${game_name}' into ${target_dir}"
    list_games
    sync_running_steam
    ;;
  *)
    usage
    ;;
esac


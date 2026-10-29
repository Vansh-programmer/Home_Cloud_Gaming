#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // 1-CLICK LINUX NATIVE CLIENT LAUNCHER
# ==============================================================================
set -euo pipefail

DEFAULT_SERVER_URL="__SERVER_URL__"
DEFAULT_TARGET_HOST="__TARGET_HOST__"

if [[ "$DEFAULT_SERVER_URL" == "__SERVER_URL__" ]]; then
  DEFAULT_SERVER_URL="https://play.vanshdev.online"
fi
if [[ "$DEFAULT_TARGET_HOST" == "__TARGET_HOST__" ]]; then
  DEFAULT_TARGET_HOST="play.vanshdev.online"
fi

SERVER_URL="${1:-$DEFAULT_SERVER_URL}"
TARGET_HOST="${2:-$DEFAULT_TARGET_HOST}"

echo "+----------------------------------------------------------------------------+"
echo "| RYOKU CLOUD GAMING // NATIVE MOONLIGHT CLIENT (120 FPS SUB-2MS)            |"
echo "+----------------------------------------------------------------------------+"
echo "  Server URL  : $SERVER_URL"
echo "  Moonlight IP: $TARGET_HOST"
echo ""

# 1. Detect Tailscale IP if available
if command -v tailscale >/dev/null 2>&1; then
  TS_IP=$(tailscale ip -4 2>/dev/null || true)
  if [[ -n "$TS_IP" && "$TARGET_HOST" == "127.0.0.1" ]]; then
    TARGET_HOST="$TS_IP"
    echo "[OK] Tailscale WireGuard detected: $TARGET_HOST"
  fi
fi

# 2. Check for Moonlight
if ! command -v moonlight >/dev/null 2>&1 && ! command -v moonlight-qt >/dev/null 2>&1; then
  echo "[NOTE] Moonlight not detected. For sub-2ms 120 FPS streaming, please install:"
  echo "  Arch/CachyOS : sudo pacman -S moonlight-qt"
  echo "  Ubuntu/Debian: sudo apt install moonlight-qt"
  echo "  Fedora       : sudo dnf install moonlight-qt"
  echo ""
fi

# 3. Check if local ryoku_client.py exists, or download it if running standalone
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$HOME/.local/share/ryoku")"
if [[ -f "$SCRIPT_DIR/ryoku_client.py" ]]; then
  exec python3 "$SCRIPT_DIR/ryoku_client.py" --server "$SERVER_URL" --host "$TARGET_HOST"
fi

# Fallback: Launch standalone web app window via browser app mode
if command -v google-chrome >/dev/null 2>&1; then
  exec google-chrome --app="$SERVER_URL"
elif command -v chromium >/dev/null 2>&1; then
  exec chromium --app="$SERVER_URL"
elif command -v brave-browser >/dev/null 2>&1; then
  exec brave-browser --app="$SERVER_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  exec xdg-open "$SERVER_URL"
fi

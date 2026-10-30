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
  DEFAULT_TARGET_HOST="100.89.198.41"
fi

SERVER_URL="${1:-$DEFAULT_SERVER_URL}"
TARGET_HOST="${2:-$DEFAULT_TARGET_HOST}"

echo "+----------------------------------------------------------------------------+"
echo "| RYOKU CLOUD GAMING // NATIVE MOONLIGHT CLIENT (120 FPS SUB-2MS)            |"
echo "+----------------------------------------------------------------------------+"
echo "  Server URL  : $SERVER_URL"

# 1. Discover host's direct streaming IP if TARGET_HOST is a Cloudflare web domain
if [[ "$TARGET_HOST" =~ \.(online|com|net|org|dev|app|io)$ || "$TARGET_HOST" == "127.0.0.1" ]]; then
  DISCOVERED_HOST=$(curl -fsSL --connect-timeout 2 "$SERVER_URL/api/client/endpoint" 2>/dev/null | grep -o '"recommended_host": *"[^"]*"' | cut -d'"' -f4 || true)
  if [[ -n "$DISCOVERED_HOST" && "$DISCOVERED_HOST" != "127.0.0.1" ]]; then
    TARGET_HOST="$DISCOVERED_HOST"
  fi
fi

echo "  Target Host : $TARGET_HOST (Moonlight UDP)"
echo ""

# 2. Check for Moonlight
HAS_MOONLIGHT=0
if command -v moonlight >/dev/null 2>&1 || command -v moonlight-qt >/dev/null 2>&1; then
  HAS_MOONLIGHT=1
  echo "[OK] Moonlight engine found."
elif command -v flatpak >/dev/null 2>&1 && flatpak info com.moonlight_stream.Moonlight >/dev/null 2>&1; then
  HAS_MOONLIGHT=1
  echo "[OK] Moonlight Flatpak found."
fi

if [[ "$HAS_MOONLIGHT" -eq 0 ]]; then
  echo "[NOTE] Moonlight not detected. For sub-2ms 120 FPS streaming, please install:"
  echo "  Arch/CachyOS : sudo pacman -S moonlight-qt"
  echo "  Ubuntu/Debian: sudo apt install moonlight-qt"
  echo "  Fedora       : flatpak install flathub com.moonlight_stream.Moonlight"
  echo ""
fi

# 3. Locate or download ryoku_client.py
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$HOME/.local/share/ryoku")"
CLIENT_PY=""

if [[ -f "$SCRIPT_DIR/ryoku_client.py" ]]; then
  CLIENT_PY="$SCRIPT_DIR/ryoku_client.py"
elif [[ -f "$SCRIPT_DIR/client/ryoku_client.py" ]]; then
  CLIENT_PY="$SCRIPT_DIR/client/ryoku_client.py"
else
  mkdir -p "$HOME/.local/share/ryoku"
  echo "[RYOKU] Fetching latest Ryoku client runtime..."
  curl -fsSL "$SERVER_URL/client/ryoku_client.py" -o "$HOME/.local/share/ryoku/ryoku_client.py" 2>/dev/null || true
  if [[ -f "$HOME/.local/share/ryoku/ryoku_client.py" ]]; then
    CLIENT_PY="$HOME/.local/share/ryoku/ryoku_client.py"
  fi
fi

# 4. Launch Native Moonlight Client (Zero WebRTC, Zero Browser)
if [[ -n "$CLIENT_PY" ]]; then
  echo "[RYOKU] Starting native 120 FPS Ryoku client (Moonlight UDP)..."
  exec python3 "$CLIENT_PY" --server "$SERVER_URL" --host "$TARGET_HOST" "$@"
else
  echo "[ERROR] Ryoku client script not found."
  exit 1
fi

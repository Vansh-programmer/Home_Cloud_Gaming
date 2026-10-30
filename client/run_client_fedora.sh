#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // 1-CLICK FEDORA NATIVE CLIENT LAUNCHER
# ==============================================================================
# Tailored specifically for Fedora Workstation, Silverblue, Nobara & RHEL.
# Supports native DNF packages, Flathub Flatpak, and hardware NVDEC/VAAPI.
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
echo "| RYOKU CLOUD GAMING // FEDORA 1-CLICK NATIVE LAUNCHER (120 FPS SUB-2MS)     |"
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

# 2. Check for Moonlight (Native binary or Flathub Flatpak)
HAS_MOONLIGHT=0
if command -v moonlight-qt >/dev/null 2>&1 || command -v moonlight >/dev/null 2>&1; then
  HAS_MOONLIGHT=1
  echo "[OK] Native Moonlight installation found."
elif command -v flatpak >/dev/null 2>&1 && flatpak info com.moonlight_stream.Moonlight >/dev/null 2>&1; then
  HAS_MOONLIGHT=1
  echo "[OK] Moonlight Flatpak (Flathub) found."
fi

if [[ "$HAS_MOONLIGHT" -eq 0 ]]; then
  echo "[RYOKU] Moonlight engine not detected on Fedora."
  echo "[RYOKU] Installing Moonlight via Flatpak (recommended for Fedora)..."
  if command -v flatpak >/dev/null 2>&1; then
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo || true
    flatpak install -y flathub com.moonlight_stream.Moonlight || true
    if flatpak info com.moonlight_stream.Moonlight >/dev/null 2>&1; then
      HAS_MOONLIGHT=1
      echo "[OK] Moonlight Flatpak installed successfully."
    fi
  fi

  # Fallback to DNF COPR if flatpak did not succeed
  if [[ "$HAS_MOONLIGHT" -eq 0 ]] && command -v dnf >/dev/null 2>&1; then
    echo "[RYOKU] Trying DNF COPR ferdiu/moonlight..."
    sudo dnf copr enable -y ferdiu/moonlight || true
    sudo dnf install -y moonlight-qt || true
  fi
fi

# 3. Check for PyGObject & WebKit2 dependencies on Fedora
has_webkit() {
  python3 -c "
import gi
gi.require_version('Gtk', '3.0')
for v in ['4.1', '4.0']:
    try:
        gi.require_version('WebKit2', v)
        from gi.repository import Gtk, WebKit2
        exit(0)
    except Exception:
        continue
exit(1)
" 2>/dev/null
}

if ! has_webkit; then
  echo "[RYOKU] Installing python3-gobject & webkit2gtk4.1 for dedicated Fedora client window..."
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3-gobject webkit2gtk4.1 || true
  fi
fi

# 4. Locate or download Ryoku Native Client application
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

# 5. Launch Native Ryoku Moonlight Client (Zero WebRTC, Zero Browser)
if [[ -n "$CLIENT_PY" ]]; then
  echo "[RYOKU] Starting native 120 FPS Ryoku client (Moonlight UDP)..."
  exec python3 "$CLIENT_PY" --server "$SERVER_URL" --host "$TARGET_HOST" "$@"
else
  echo "[ERROR] Could not find Ryoku native client runtime."
  exit 1
fi

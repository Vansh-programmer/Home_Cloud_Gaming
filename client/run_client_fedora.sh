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
  DEFAULT_TARGET_HOST="play.vanshdev.online"
fi

SERVER_URL="${1:-$DEFAULT_SERVER_URL}"
TARGET_HOST="${2:-$DEFAULT_TARGET_HOST}"

echo "+----------------------------------------------------------------------------+"
echo "| RYOKU CLOUD GAMING // FEDORA 1-CLICK NATIVE LAUNCHER (120 FPS SUB-2MS)     |"
echo "+----------------------------------------------------------------------------+"
echo "  Server URL  : $SERVER_URL"
echo "  Target Host : $TARGET_HOST"
echo ""

# 1. Detect Tailscale mesh if available
if command -v tailscale >/dev/null 2>&1; then
  TS_IP=$(tailscale ip -4 2>/dev/null || true)
  if [[ -n "$TS_IP" && "$TARGET_HOST" == "127.0.0.1" ]]; then
    TARGET_HOST="$TS_IP"
    echo "[OK] Tailscale WireGuard detected: $TARGET_HOST"
  fi
fi

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
if command -v dnf >/dev/null 2>&1; then
  if ! python3 -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null && \
     ! python3 -c "import gi; gi.require_version('WebKit2', '4.0')" 2>/dev/null; then
    echo "[NOTE] Installing python3-gobject & webkit2gtk4.1 for dedicated Fedora client window..."
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

# 5. Launch Native GTK Client Window if environment is supported
if [[ -n "$CLIENT_PY" ]] && python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null; then
  echo "[RYOKU] Launching native Ryoku client..."
  exec python3 "$CLIENT_PY" --server "$SERVER_URL" --host "$TARGET_HOST"
fi

# 6. Fallback: Dedicated browser app mode (Chromium / Chrome / Brave / Firefox)
echo "[RYOKU] Opening Ryoku Console in standalone application window..."
if command -v google-chrome >/dev/null 2>&1; then
  exec google-chrome --app="$SERVER_URL"
elif command -v chromium >/dev/null 2>&1; then
  exec chromium --app="$SERVER_URL"
elif command -v chromium-browser >/dev/null 2>&1; then
  exec chromium-browser --app="$SERVER_URL"
elif command -v brave-browser >/dev/null 2>&1; then
  exec brave-browser --app="$SERVER_URL"
elif command -v firefox >/dev/null 2>&1; then
  exec firefox --new-window "$SERVER_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  exec xdg-open "$SERVER_URL"
else
  echo "[ERROR] Could not find a suitable browser or GTK runtime to launch Ryoku."
  exit 1
fi

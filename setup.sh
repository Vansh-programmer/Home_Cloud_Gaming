#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // UNIVERSAL DISTRO SETUP SCRIPT
# ==============================================================================
# Automatically detects your Linux distribution, installs all required packages
# (Bubblewrap, Weston, PipeWire, GStreamer WebRTC, Python, SDL2), checks GPU
# hardware acceleration, and compiles the built-in 3D arena game.
# ==============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "+----------------------------------------------------------------------------+"
echo "| RYOKU CLOUD GAMING // AUTOMATED ENVIRONMENT INSTALLER                      |"
echo "+----------------------------------------------------------------------------+"

# 1. Detect distribution
if [[ ! -f /etc/os-release ]]; then
  echo "[ERROR] Cannot detect Linux distribution (/etc/os-release missing)." >&2
  exit 1
fi

source /etc/os-release
DISTRO_ID="${ID:-unknown}"
DISTRO_LIKE="${ID_LIKE:-}"

echo "[DETECT] Detected Linux Distribution: ${PRETTY_NAME:-$DISTRO_ID}"

install_packages() {
  case "$DISTRO_ID" in
    arch|cachyos|manjaro|endeavouros|artix)
      echo "[INSTALL] Installing dependencies via pacman..."
      sudo pacman -S --needed --noconfirm \
        bubblewrap weston xorg-server-xwayland \
        pipewire pipewire-pulse wireplumber \
        gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav \
        python python-gobject python-aiohttp \
        sdl2 glu mesa-utils gcc tailscale
      ;;
    ubuntu|debian|pop|linuxmint|elementary|zorin)
      echo "[INSTALL] Installing dependencies via apt..."
      sudo apt-get update
      sudo apt-get install -y \
        bubblewrap weston xwayland \
        pipewire pipewire-pulse wireplumber \
        gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-vaapi \
        libgstreamer1.0-0 libgstreamer-plugins-bad1.0-0 \
        gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-gst-plugins-bad-1.0 \
        python3 python3-aiohttp python3-gi python3-gi-cairo \
        libsdl2-dev libglu1-mesa-dev gcc
      ;;
    fedora|nobara)
      echo "[INSTALL] Installing dependencies via dnf..."
      sudo dnf install -y \
        bubblewrap weston xorg-x11-server-Xwayland \
        pipewire pipewire-pulseaudio wireplumber \
        gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugins-bad-free \
        gstreamer1-plugins-ugly-free gstreamer1-vaapi \
        python3 python3-aiohttp python3-gobject \
        SDL2-devel mesa-libGLU-devel gcc
      ;;
    opensuse*|suse)
      echo "[INSTALL] Installing dependencies via zypper..."
      sudo zypper install -y \
        bubblewrap weston xwayland \
        pipewire pipewire-pulseaudio wireplumber \
        gstreamer-plugins-base gstreamer-plugins-good gstreamer-plugins-bad \
        gstreamer-plugins-ugly gstreamer-plugins-vaapi \
        python3 python3-aiohttp python3-gobject \
        libSDL2-devel Mesa-libGLU-devel gcc
      ;;
    *)
      # Check ID_LIKE fallback
      if [[ "$DISTRO_LIKE" == *"arch"* ]]; then
        sudo pacman -S --needed --noconfirm bubblewrap weston xorg-server-xwayland pipewire pipewire-pulse wireplumber gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav python python-gobject python-aiohttp sdl2 glu mesa-utils gcc
      elif [[ "$DISTRO_LIKE" == *"debian"* ]] || [[ "$DISTRO_LIKE" == *"ubuntu"* ]]; then
        sudo apt-get update && sudo apt-get install -y bubblewrap weston xwayland pipewire pipewire-pulse wireplumber gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav python3 python3-aiohttp python3-gi libsdl2-dev gcc
      elif [[ "$DISTRO_LIKE" == *"fedora"* ]] || [[ "$DISTRO_LIKE" == *"rhel"* ]]; then
        sudo dnf install -y bubblewrap weston xorg-x11-server-Xwayland pipewire pipewire-pulseaudio wireplumber gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugins-bad-free python3 python3-aiohttp python3-gobject SDL2-devel gcc
      else
        echo "[WARN] Unsupported distribution '$DISTRO_ID'. Please install dependencies manually (see UNIVERSAL_LINUX_SETUP.md)."
      fi
      ;;
  esac
}

install_packages

# 2. Check Hardware Encoders
echo "[HARDWARE] Inspecting available video encoders..."
if command -v gst-inspect-1.0 >/dev/null 2>&1; then
  if gst-inspect-1.0 nvh264enc >/dev/null 2>&1; then
    echo "  [+] NVIDIA NVENC H.264 (nvh264enc): Available (Ultra-Low Latency GPU Encode)"
  elif gst-inspect-1.0 vaapih264enc >/dev/null 2>&1; then
    echo "  [+] Intel/AMD VA-API H.264 (vaapih264enc): Available (Hardware GPU Encode)"
  elif gst-inspect-1.0 vah264enc >/dev/null 2>&1; then
    echo "  [+] Modern VA-API H.264 (vah264enc): Available (Hardware GPU Encode)"
  else
    echo "  [!] No hardware H.264 encoder detected. Software CPU fallback (x264enc) will be used."
  fi
fi

# 3. Compile 3D Test Game (CyberArena 3D)
echo "[BUILD] Compiling CyberArena 3D..."
mkdir -p "$PROJECT_DIR/data/logs" "$PROJECT_DIR/data/users" "$PROJECT_DIR/data/shared_steam_library/steamapps"
if [[ -f "$PROJECT_DIR/engine/test_game/arena3d.c" ]]; then
  gcc -O2 "$PROJECT_DIR/engine/test_game/arena3d.c" -o "$PROJECT_DIR/engine/test_game/arena3d" -lSDL2 -lGL -lGLU -lm
  echo "  [+] CyberArena 3D compiled successfully."
fi

# 4. Verify unprivileged Bubblewrap sandbox capability
echo "[SANDBOX] Verifying Bubblewrap isolation capability..."
if bwrap --ro-bind / / --dev /dev --proc /proc echo "OK" >/dev/null 2>&1; then
  echo "  [+] Bubblewrap unprivileged user namespace: Functional"
else
  echo "  [!] Bubblewrap cannot create unprivileged user namespaces."
  echo "      Run: sudo sysctl kernel.unprivileged_userns_clone=1"
fi

echo ""
echo "+----------------------------------------------------------------------------+"
echo "| SETUP COMPLETE // READY TO LAUNCH                                          |"
echo "|   To start the cloud gaming server, run:                                  |"
echo "|     ./start.sh                                                             |"
echo "|                                                                            |"
echo "|   Full multi-distro guide: UNIVERSAL_LINUX_SETUP.md                        |"
echo "+----------------------------------------------------------------------------+"


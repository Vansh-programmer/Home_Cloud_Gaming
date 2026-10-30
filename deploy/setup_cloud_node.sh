#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // COMPUTE NODE PROVISIONING SCRIPT (STEAM + HEROIC + WEB)
# ==============================================================================
# Provisions this Linux PC as a dedicated, fully isolated Cloud Gaming Node:
#   - Games on Whales (Wolf) GameStream server
#   - Moonlight Web in-browser client (WebCodecs + WASM) on port 8080
#   - Steam Cloud & Heroic Games Launcher (Epic & GOG) on-demand containers
#   - Shared Read-Only game storage (Zero file duplication, zero user tampering)
#   - Isolated Per-User storage for independent logins & savegames
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================================================"
echo "  RYOKU CLOUD GAMING // COMPUTE NODE PROVISIONING (STEAM + HEROIC + WEB)"
echo "========================================================================"

# 1. Verify NVIDIA Driver & Modeset
if [[ -f /sys/module/nvidia/version ]]; then
  NV_VERSION="$(cat /sys/module/nvidia/version)"
  echo "[OK] NVIDIA GPU Driver Detected: ${NV_VERSION}"
else
  echo "[ERROR] NVIDIA driver not detected. Ensure proprietary drivers are loaded."
  exit 1
fi

if [[ -f /sys/module/nvidia_drm/parameters/modeset ]]; then
  MODESET="$(cat /sys/module/nvidia_drm/parameters/modeset)"
  if [[ "$MODESET" == "Y" || "$MODESET" == "1" ]]; then
    echo "[OK] NVIDIA DRM Modeset Enabled (${MODESET})"
  else
    echo "[WARNING] NVIDIA DRM Modeset is disabled. Recommended for headless rendering."
  fi
fi

# 2. Verify Docker Daemon
if ! docker info >/dev/null 2>&1; then
  echo ""
  echo "------------------------------------------------------------------------"
  echo "[ACTION REQUIRED] Docker daemon is not running or lacks user permissions."
  echo "Please run this command in your host terminal:"
  echo ""
  echo "  sudo systemctl enable --now docker && sudo usermod -aG docker \$USER"
  echo ""
  echo "Then run this script again."
  echo "------------------------------------------------------------------------"
  exit 1
fi
echo "[OK] Docker daemon is active."

# 3. Setup Virtual Gamepad Udev Rules (/dev/uinput & /dev/uhid)
UDEV_RULE_PATH="/etc/udev/rules.d/85-wolf.rules"
if [[ ! -f "$UDEV_RULE_PATH" ]]; then
  echo "[INFO] Installing controller udev rules for virtual gamepads..."
  if command -v sudo >/dev/null 2>&1; then
    sudo curl -fsSL https://raw.githubusercontent.com/games-on-whales/wolf/stable/85-wolf.rules -o "$UDEV_RULE_PATH" 2>/dev/null || true
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    echo "[OK] Controller udev rules configured."
  else
    echo "[NOTICE] Skipping udev rule install (requires sudo). Ensure /dev/uinput is accessible."
  fi
else
  echo "[OK] Controller udev rules already present."
fi

# 4. Provision NVIDIA Driver Volume (Matches exact host driver version)
echo "[INFO] Checking nvidia-driver-vol for version ${NV_VERSION}..."
if ! docker volume inspect nvidia-driver-vol >/dev/null 2>&1; then
  docker volume create nvidia-driver-vol
  echo "[OK] Created volume: nvidia-driver-vol"
fi

echo "[INFO] Generating driver libraries container..."
curl -fsSL https://raw.githubusercontent.com/games-on-whales/gow/master/images/nvidia-driver/Dockerfile | \
  docker build -t "gow/nvidia-driver:${NV_VERSION}" -f - --build-arg "NV_VERSION=${NV_VERSION}" .

echo "[INFO] Populating nvidia-driver-vol..."
docker run --rm --mount source=nvidia-driver-vol,destination=/usr/nvidia "gow/nvidia-driver:${NV_VERSION}" sh -c 'echo "Driver libraries populated."'

# 5. Ensure Shared Games Directory Exists (Read-Only to users)
mkdir -p "$PROJECT_DIR/data/shared_games"
echo "[OK] Shared games storage directory ready at data/shared_games (Mounted :ro into containers)"

# 6. Ensure Per-User Named Volume Exists
if ! docker volume inspect ryoku-user-storage >/dev/null 2>&1; then
  docker volume create ryoku-user-storage
  echo "[OK] Created isolated per-user storage volume: ryoku-user-storage"
fi

# 7. Pre-pull Core Container Stack
echo "[INFO] Pre-pulling Games on Whales Wolf server, Moonlight Web, Steam, & Heroic..."
docker compose pull
docker pull ghcr.io/games-on-whales/steam:edge
docker pull ghcr.io/games-on-whales/heroic-games-launcher:edge

echo ""
echo "========================================================================"
echo "  RYOKU CLOUD GAMING NODE READY!"
echo "========================================================================"
echo "Start the cloud gaming platform:"
echo "  docker compose up -d"
echo ""
echo "Play via Web Browser (Moonlight Web):"
echo "  Open: http://localhost:8080   (or http://100.89.198.41:8080 over Tailscale)"
echo ""
echo "Play via Native Moonlight App:"
echo "  Add Host IP: 100.89.198.41"
echo "========================================================================"

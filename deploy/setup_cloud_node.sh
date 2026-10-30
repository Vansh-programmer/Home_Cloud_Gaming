#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // COMPUTE NODE PROVISIONING SCRIPT (STEAM + HEROIC + WEB)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================================================"
echo "  RYOKU CLOUD GAMING // COMPUTE NODE PROVISIONING (NVIDIA + DOCKER)"
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

# 2. Check and Install NVIDIA Container Toolkit
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  echo ""
  echo "[ACTION REQUIRED] nvidia-container-toolkit is missing."
  echo "Installing nvidia-container-toolkit via pacman..."
  if command -v sudo >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    sudo chmod 666 /var/run/docker.sock
    echo "[OK] NVIDIA Container Toolkit installed and Docker configured."
  else
    echo "[ERROR] Please run manually: sudo pacman -S nvidia-container-toolkit && sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
    exit 1
  fi
else
  echo "[OK] nvidia-container-toolkit detected."
fi

# 3. Setup Virtual Gamepad Udev Rules (/dev/uinput & /dev/uhid)
UDEV_RULE_PATH="/etc/udev/rules.d/85-wolf.rules"
if [[ ! -f "$UDEV_RULE_PATH" ]]; then
  echo "[INFO] Installing controller udev rules for virtual gamepads..."
  if command -v sudo >/dev/null 2>&1; then
    sudo curl -fsSL https://raw.githubusercontent.com/games-on-whales/wolf/stable/85-wolf.rules -o "$UDEV_RULE_PATH" 2>/dev/null || true
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    echo "[OK] Controller udev rules configured."
  fi
else
  echo "[OK] Controller udev rules already present."
fi

# 4. Ensure Shared Games Directory Exists (Read-Only to users)
mkdir -p "$PROJECT_DIR/data/shared_games"
echo "[OK] Shared games directory ready at data/shared_games (Mounted :ro into containers)"

# 5. Ensure Per-User Named Volume Exists
if ! docker volume inspect ryoku-user-storage >/dev/null 2>&1; then
  docker volume create ryoku-user-storage
  echo "[OK] Created isolated per-user storage volume: ryoku-user-storage"
fi

# 6. Pre-pull Core Container Stack
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
echo "========================================================================"

#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // GAMES ON WHALES (WOLF) SETUP
# ==============================================================================
# Sets up Docker, NVIDIA driver volume, and controller udev rules for Wolf.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "============================================================"
echo "  RYOKU CLOUD GAMING // GAMES ON WHALES (WOLF) SETUP"
echo "============================================================"

# 1. Check NVIDIA Driver & Modeset
if [[ -f /sys/module/nvidia/version ]]; then
  NV_VERSION="$(cat /sys/module/nvidia/version)"
  echo "[OK] Host NVIDIA Driver Version: ${NV_VERSION}"
else
  echo "[ERROR] NVIDIA driver kernel module not loaded!"
  exit 1
fi

if [[ -f /sys/module/nvidia_drm/parameters/modeset ]]; then
  MODESET="$(cat /sys/module/nvidia_drm/parameters/modeset)"
  if [[ "$MODESET" == "Y" || "$MODESET" == "1" ]]; then
    echo "[OK] NVIDIA DRM Modeset is enabled (${MODESET})"
  else
    echo "[WARNING] NVIDIA DRM Modeset is NOT enabled (${MODESET}). Required for Wayland/Gamescope streaming."
  fi
fi

# 2. Check Docker Daemon
if ! docker info >/dev/null 2>&1; then
  echo ""
  echo "[ACTION REQUIRED] Docker daemon is not running or current user lacks docker group permissions."
  echo "Please run the following commands in your host terminal:"
  echo ""
  echo "  sudo systemctl enable --now docker"
  echo "  sudo usermod -aG docker \$USER"
  echo ""
  echo "Then run this script again."
  exit 1
fi

echo "[OK] Docker daemon is running."

# 3. Create and Populate nvidia-driver-vol
echo "[INFO] Setting up NVIDIA driver volume: nvidia-driver-vol for version ${NV_VERSION}..."
if ! docker volume inspect nvidia-driver-vol >/dev/null 2>&1; then
  docker volume create nvidia-driver-vol
  echo "[OK] Created docker volume nvidia-driver-vol"
else
  echo "[INFO] Volume nvidia-driver-vol already exists."
fi

echo "[INFO] Building driver helper container..."
curl -fsSL https://raw.githubusercontent.com/games-on-whales/gow/master/images/nvidia-driver/Dockerfile | \
  docker build -t "gow/nvidia-driver:${NV_VERSION}" -f - --build-arg "NV_VERSION=${NV_VERSION}" .

echo "[INFO] Populating nvidia-driver-vol with host libraries..."
docker run --rm --mount source=nvidia-driver-vol,destination=/usr/nvidia "gow/nvidia-driver:${NV_VERSION}" sh -c 'echo "Driver libraries synced."'

# 4. Pull Wolf Images
echo "[INFO] Pulling Wolf GameStream container..."
docker compose pull

echo ""
echo "============================================================"
echo "  GAMES ON WHALES (WOLF) SETUP COMPLETE!"
echo "============================================================"
echo "To start the gaming server:"
echo "  docker compose up -d"
echo ""
echo "To check logs and view Moonlight pairing PIN:"
echo "  docker compose logs -f wolf"
echo ""
echo "To stop:"
echo "  docker compose down"
echo "============================================================"

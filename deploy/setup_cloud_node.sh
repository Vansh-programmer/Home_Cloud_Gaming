#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // COMPUTE NODE PROVISIONING SCRIPT (GAMES ON WHALES)
# ==============================================================================
# Provisions this Linux PC as a dedicated, fully isolated Cloud Gaming Node.
#
# Key Features:
#   - Zero personal files or host Steam libraries mounted.
#   - Ephemeral containerized gaming sessions (ghcr.io/games-on-whales).
#   - RTX 4060 GPU hardware encoding & Vulkan passthrough via nvidia-driver-vol.
#   - Dedicated virtual gamepad mapping (/dev/uinput & /dev/uhid).
#   - Wolf-Den Web Console on port 8080 for pairing & session monitoring.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================================================"
echo "  RYOKU CLOUD GAMING // COMPUTE NODE INITIALIZATION (GOW WOLF)"
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
    echo "[OK] Udev rules configured."
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

# 5. Provision Fresh Cloud Gaming Named Volume
if ! docker volume inspect ryoku-cloud-storage >/dev/null 2>&1; then
  docker volume create ryoku-cloud-storage
  echo "[OK] Created fresh cloud gaming storage volume: ryoku-cloud-storage"
else
  echo "[OK] Cloud storage volume exists: ryoku-cloud-storage"
fi

# 6. Pull Cloud Gaming Containers
echo "[INFO] Pulling Games on Whales Wolf server & Steam cloud images..."
docker compose pull
docker pull ghcr.io/games-on-whales/steam:edge

echo ""
echo "========================================================================"
echo "  RYOKU CLOUD GAMING NODE READY!"
echo "========================================================================"
echo "Start the cloud gaming platform:"
echo "  docker compose up -d"
echo ""
echo "Open the Admin Console in browser (for Moonlight pairing & metrics):"
echo "  http://localhost:8080   (or http://100.89.198.41:8080 over Tailscale)"
echo ""
echo "Connect with Moonlight:"
echo "  Add host IP: 100.89.198.41"
echo "  Enter PIN in Wolf-Den Admin Console or via 'docker compose logs -f wolf'"
echo "========================================================================"


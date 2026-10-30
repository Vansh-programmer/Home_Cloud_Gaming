#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // HOST PC AUTOMATED STARTUP SCRIPT
# ==============================================================================
# Essential startup script to execute when your Host Gaming PC powers on.
#
# Automatically configures and launches:
#   1. Kernel & Input Devices (/dev/uinput permission for virtual gamepads/mice)
#   2. Audio Daemons (PipeWire / PulseAudio low-latency virtual monitors)
#   3. Game Synchronization (Syncs Steam & Heroic libraries into Sunshine apps.json)
#   4. Sunshine GameStream Server (UDP 47998-48010 for 120 FPS Moonlight streaming)
#   5. Network & Direct Mesh (Tailscale WireGuard P2P + Cloudflare Tunnel)
#   6. Ryoku WebRTC Server & Web App (Port 8080)
#
# Usage:
#   ./deploy/host_autostart.sh            # Run now (starts everything in background)
#   sudo ./deploy/host_autostart.sh --install   # Enable 100% automatic start on PC boot
#   ./deploy/host_autostart.sh --status   # Check status of all host services
#   ./deploy/host_autostart.sh --stop     # Stop all running services
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# Source environment configuration if present (.env)
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

PORT="${PORT:-8080}"
ADMIN_USER="${ADMIN_USER:-vansh}"
ADMIN_PASS="${ADMIN_PASS:-ryoku-admin-2026}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-vanshdev.online/cloudgaming}"
CF_CONFIG="$PROJECT_DIR/deploy/cloudflared-config.yml"
LOG_DIR="$PROJECT_DIR/data/logs"
RUN_AS_USER="${SUDO_USER:-$USER}"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data/users" "$PROJECT_DIR/data/shared_steam_library/steamapps"

print_header() {
  echo "+----------------------------------------------------------------------------+"
  echo "| RYOKU CLOUD GAMING // HOST PC AUTOMATED STARTUP                            |"
  echo "+----------------------------------------------------------------------------+"
}

# ==============================================================================
# 1. HARDWARE & INPUT PERMISSIONS (CRITICAL FOR GAMEPAD/MOUSE EMULATION)
# ==============================================================================
setup_hardware() {
  echo "[HARDWARE] Checking virtual input device (/dev/uinput)..."

  # Ensure uinput kernel module is loaded
  if ! lsmod | grep -q "^uinput" 2>/dev/null; then
    echo "[HARDWARE] Loading uinput kernel module..."
    if command -v sudo >/dev/null 2>&1; then
      sudo modprobe uinput 2>/dev/null || true
    else
      modprobe uinput 2>/dev/null || true
    fi
  fi

  # Ensure /dev/uinput is writable so Sunshine and virtual gamepad drivers can simulate input
  if [[ -e /dev/uinput && ! -w /dev/uinput ]]; then
    echo "[HARDWARE] Granting write permissions to /dev/uinput..."
    if command -v sudo >/dev/null 2>&1; then
      sudo chmod 0666 /dev/uinput 2>/dev/null || true
    fi
  fi

  # Install persistent udev rule if root/sudo available
  UDEV_RULE="/etc/udev/rules.d/85-sunshine-input.rules"
  if [[ -d /etc/udev/rules.d ]] && [[ ! -f "$UDEV_RULE" ]]; then
    echo "[HARDWARE] Installing persistent udev rule for virtual controllers..."
    if command -v sudo >/dev/null 2>&1; then
      echo 'KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess", MODE="0666"' | sudo tee "$UDEV_RULE" >/dev/null 2>&1 || true
      sudo udevadm control --reload-rules 2>/dev/null || true
      sudo udevadm trigger 2>/dev/null || true
    fi
  fi
}

# ==============================================================================
# 2. AUDIO ENVIRONMENT
# ==============================================================================
setup_audio() {
  # Set XDG_RUNTIME_DIR if not already present
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u "$RUN_AS_USER")}"
  if [[ -d "$XDG_RUNTIME_DIR" ]]; then
    export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
  fi
}

# ==============================================================================
# 3. BUILD TEST GAME & COMPILE REQUIRED BINARIES
# ==============================================================================
build_dependencies() {
  if [[ ! -x "$PROJECT_DIR/engine/test_game/arena3d" ]] || [[ "$PROJECT_DIR/engine/test_game/arena3d.c" -nt "$PROJECT_DIR/engine/test_game/arena3d" ]]; then
    echo "[BUILD] Compiling CyberArena 3D (OpenGL + SDL2)..."
    gcc -O2 "$PROJECT_DIR/engine/test_game/arena3d.c" -o "$PROJECT_DIR/engine/test_game/arena3d" -lSDL2 -lGL -lGLU -lm 2>/dev/null || true
  fi
}

# ==============================================================================
# 4. SUNSHINE GAMESTREAM SERVER (MOONLIGHT HOST)
# ==============================================================================
start_sunshine() {
  if command -v sunshine >/dev/null 2>&1; then
    echo "[SUNSHINE] Syncing Steam & Heroic games to Sunshine apps.json..."
    python3 "$PROJECT_DIR/backend/sunshine_sync.py" >/dev/null 2>&1 || true

    if ! pgrep -x sunshine >/dev/null 2>&1; then
      echo "[SUNSHINE] Starting Sunshine GameStream server..."
      setsid nohup sunshine > "$LOG_DIR/sunshine.log" 2>&1 &
      disown $! 2>/dev/null || true
      sleep 1
      echo "[SUNSHINE] Online (Moonlight UDP streaming ready on ports 47998-48010)."
    else
      echo "[SUNSHINE] Already active."
    fi
  else
    echo "[SUNSHINE] Not installed. (Optional: install sunshine for 120 FPS native Moonlight)."
  fi
}

# ==============================================================================
# 5. TAILSCALE WIREGUARD MESH (DIRECT ZERO-LAG P2P)
# ==============================================================================
check_tailscale() {
  if command -v tailscale >/dev/null 2>&1; then
    TS_IP=$(tailscale ip -4 2>/dev/null || true)
    if [[ -z "$TS_IP" ]]; then
      echo "[TAILSCALE] Starting Tailscale daemon..."
      sudo systemctl start tailscaled 2>/dev/null || true
      TS_IP=$(tailscale ip -4 2>/dev/null || true)
    fi
    if [[ -n "$TS_IP" ]]; then
      echo "[TAILSCALE] Online -> IP: $TS_IP"
    fi
  fi
}

# ==============================================================================
# 6. CLOUDFLARE TUNNEL (SECURE PUBLIC GATEWAY)
# ==============================================================================
start_tunnel() {
  if command -v cloudflared >/dev/null 2>&1 && [[ -f "$CF_CONFIG" ]]; then
    CRED_FILE=$( awk -F': ' '/credentials-file:/ {print $2}' "$CF_CONFIG" 2>/dev/null | tr -d ' "' || true )
    if [[ -n "$CRED_FILE" && -f "$CRED_FILE" ]]; then
      if ! pgrep -f "cloudflared.*deploy/cloudflared-config.yml" >/dev/null 2>&1; then
        echo "[TUNNEL] Starting Cloudflare Tunnel..."
        setsid nohup cloudflared tunnel --config "$CF_CONFIG" run > "$LOG_DIR/tunnel.log" 2>&1 &
        disown $! 2>/dev/null || true
        echo "[TUNNEL] Online -> https://${PUBLIC_DOMAIN}"
      else
        echo "[TUNNEL] Already active."
      fi
    fi
  fi
}

# ==============================================================================
# 7. RYOKU CLOUD GAMING SERVER (WEBRTC ORCHESTRATOR & DASHBOARD)
# ==============================================================================
start_ryoku_server() {
  if pgrep -f "engine/launch_phase6.py" >/dev/null 2>&1; then
    echo "[SERVER] Stopping existing instance..."
    pkill -f "engine/launch_phase6.py" 2>/dev/null || true
    sleep 1
  fi

  echo "[SERVER] Starting Ryoku Cloud Gaming Server on port ${PORT}..."
  setsid nohup python3 "$PROJECT_DIR/engine/launch_phase6.py" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --admin-user "$ADMIN_USER" \
    --admin-password "$ADMIN_PASS" \
    --public-domain "$PUBLIC_DOMAIN" \
    > "$LOG_DIR/server.log" 2>&1 &
  SERVER_PID=$!
  disown "$SERVER_PID" 2>/dev/null || true
  sleep 1
  echo "[SERVER] Online (PID: $SERVER_PID, Log: data/logs/server.log)"
}

# ==============================================================================
# DISPLAY STATUS
# ==============================================================================
show_status() {
  print_header
  LAN_IP=$( (ip -4 route get 1.1.1.1 2>/dev/null || true) | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n 1 )
  [[ -z "$LAN_IP" ]] && LAN_IP="127.0.0.1"
  TS_IP=$(command -v tailscale >/dev/null 2>&1 && tailscale ip -4 2>/dev/null || true)

  echo "SERVICE STATUS:"
  echo -n "  Server (Port ${PORT}) : "
  if pgrep -f "engine/launch_phase6.py" >/dev/null 2>&1; then
    echo "ONLINE (PID: $(pgrep -f "engine/launch_phase6.py" | head -n 1))"
  else
    echo "OFFLINE"
  fi

  echo -n "  Sunshine (GameStream): "
  if pgrep -x sunshine >/dev/null 2>&1; then
    echo "ONLINE (UDP 47998-48010)"
  else
    echo "OFFLINE"
  fi

  echo -n "  Cloudflare Tunnel    : "
  if pgrep -f "cloudflared.*deploy/cloudflared-config.yml" >/dev/null 2>&1; then
    echo "ONLINE (https://${PUBLIC_DOMAIN})"
  else
    echo "OFFLINE"
  fi

  echo -n "  Tailscale Mesh       : "
  if [[ -n "$TS_IP" ]]; then
    echo "ONLINE (IP: ${TS_IP})"
  else
    echo "NOT CONNECTED"
  fi

  echo -n "  Virtual Input (/dev) : "
  if [[ -w /dev/uinput ]]; then
    echo "WRITABLE (Gamepad emulation ready)"
  else
    echo "RESTRICTED (Run: sudo chmod 0666 /dev/uinput)"
  fi

  echo ""
  echo "ENDPOINTS:"
  echo "  Local Browser   : http://localhost:${PORT}"
  echo "  Home Wi-Fi LAN  : http://${LAN_IP}:${PORT}"
  if [[ -n "$TS_IP" ]]; then
    echo "  Moonlight Target: ${TS_IP} (or ${LAN_IP})"
  else
    echo "  Moonlight Target: ${LAN_IP}"
  fi
  echo "  Public Gateway  : https://${PUBLIC_DOMAIN}"
}

# ==============================================================================
# STOP ALL SERVICES
# ==============================================================================
stop_all() {
  print_header
  echo "[STOP] Stopping all Ryoku Cloud Gaming host processes..."
  pkill -f "engine/launch_phase6.py" 2>/dev/null || true
  pkill -f "cloudflared.*deploy/cloudflared-config.yml" 2>/dev/null || true
  pkill -x sunshine 2>/dev/null || true
  sleep 1
  echo "[OK] All host services stopped."
}

# ==============================================================================
# INSTALL AS BOOT SERVICE (SYSTEMD)
# ==============================================================================
install_boot_service() {
  print_header
  echo "[INSTALL] Installing automatic boot service (systemd)..."

  SERVICE_FILE="/etc/systemd/system/ryoku-host.service"
  TARGET_USER="$RUN_AS_USER"

  cat <<EOF | sudo tee "$SERVICE_FILE" >/dev/null
[Unit]
Description=Ryoku Cloud Gaming — Host PC Automated Startup Stack
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=${TARGET_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="HOME=/home/${TARGET_USER}"
Environment="USER=${TARGET_USER}"
Environment="PATH=/usr/local/bin:/usr/bin:/bin:/home/${TARGET_USER}/.local/bin"
ExecStartPre=/usr/bin/bash -c "modprobe uinput 2>/dev/null || true; chmod 0666 /dev/uinput 2>/dev/null || true"
ExecStart=${PROJECT_DIR}/deploy/host_autostart.sh --start-services
ExecStop=${PROJECT_DIR}/deploy/host_autostart.sh --stop

[Install]
WantedBy=multi-user.target
EOF

  echo "[INSTALL] Created $SERVICE_FILE"
  sudo systemctl daemon-reload
  sudo systemctl enable ryoku-host.service
  sudo systemctl restart ryoku-host.service
  echo "[OK] ryoku-host.service installed and enabled to start automatically on PC boot!"
  echo ""
  show_status
}

# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================
case "${1:-}" in
  --install|-i)
    install_boot_service
    exit 0
    ;;
  --status)
    show_status
    exit 0
    ;;
  --stop)
    stop_all
    exit 0
    ;;
  --start-services)
    setup_hardware
    setup_audio
    build_dependencies
    start_sunshine
    check_tailscale
    start_tunnel
    start_ryoku_server
    exit 0
    ;;
  *)
    print_header
    setup_hardware
    setup_audio
    build_dependencies
    start_sunshine
    check_tailscale
    start_tunnel
    start_ryoku_server
    echo ""
    show_status
    echo ""
    echo "[TIP] To make this run automatically every time your PC turns on:"
    echo "      sudo ./deploy/host_autostart.sh --install"
    ;;
esac

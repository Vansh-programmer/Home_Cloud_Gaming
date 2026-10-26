#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // ONE-COMMAND LAUNCHER (start.sh)
# ==============================================================================
# Usage:
#   ./start.sh                    # Start server + Cloudflare tunnel (foreground)
#   ./start.sh --background       # Start server + Cloudflare tunnel in background
#   ./start.sh --install-service  # Install & enable auto-start on PC boot (systemd)
#   ./start.sh --stop             # Stop all running Ryoku & tunnel processes
#   ./start.sh --status           # Check live server, GPU, and tunnel status
#   ./start.sh --check-turn       # Test the TURN relay (needed for players outside your network)
# ==============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Optional local secrets/config (Cloudflare TURN keys, admin password, ...). See .env.example
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi
export ENABLE_CONTAINER_ICE="${ENABLE_CONTAINER_ICE:-1}"

PORT="${PORT:-8080}"
ADMIN_USER="${ADMIN_USER:-vansh}"
ADMIN_PASS="${ADMIN_PASS:-ryoku-admin-2026}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-vanshdev.online/cloudgaming}"
CF_CONFIG="$PROJECT_DIR/deploy/cloudflared-config.yml"
LOG_DIR="$PROJECT_DIR/data/logs"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data/users" "$PROJECT_DIR/data/shared_steam_library/steamapps"

print_banner() {
  echo "+----------------------------------------------------------------------------+"
  echo "| RYOKU CLOUD GAMING ENGINE // AUTOMATED STACK LAUNCHER                      |"
  echo "+----------------------------------------------------------------------------+"
}

stop_stack() {
  echo "[STOP] Stopping running Ryoku Cloud Gaming and cloudflared processes..."
  pkill -f "engine/launch_phase6.py" 2>/dev/null || true
  pkill -f "cloudflared.*deploy/cloudflared-config.yml" 2>/dev/null || true
  sleep 1
  echo "[OK] All processes stopped."
}

show_status() {
  print_banner
  if pgrep -af "engine/launch_phase6.py" >/dev/null 2>&1; then
    echo "[SERVER]  ONLINE  ($(pgrep -af "engine/launch_phase6.py" | head -n 1))"
  else
    echo "[SERVER]  OFFLINE"
  fi

  if pgrep -af "cloudflared" >/dev/null 2>&1; then
    echo "[TUNNEL]  ONLINE  ($(pgrep -af "cloudflared" | head -n 1))"
  else
    echo "[TUNNEL]  OFFLINE"
  fi

  if command -v curl >/dev/null 2>&1; then
    HEALTH=$(curl -s "http://127.0.0.1:${PORT}/api/health" || true)
    if [[ -n "$HEALTH" ]]; then
      echo "[HEALTH]  $HEALTH"
    fi
  fi
}

install_systemd_services() {
  print_banner
  echo "[SYSTEMD] Installing boot services to /etc/systemd/system/..."
  sudo cp "$PROJECT_DIR/deploy/ryoku-cloud-gaming.service" /etc/systemd/system/
  sudo cp "$PROJECT_DIR/deploy/ryoku-cloudflare-tunnel.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now ryoku-cloud-gaming.service
  if [[ -f "/home/$USER/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json" ]]; then
    sudo systemctl enable --now ryoku-cloudflare-tunnel.service
  else
    echo "[INFO] Cloudflare credentials JSON not found yet; enabled ryoku-cloud-gaming.service."
    echo "       To generate tunnel credentials, run:"
    echo "       cloudflared tunnel token --cred-file ~/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json vansh-cloud-gaming"
  fi
  echo "[OK] Services installed and started."
  sudo systemctl status ryoku-cloud-gaming.service --no-pager -l || true
}

# Handle CLI flags
MODE="foreground"
case "${1:-}" in
  --stop|-s)
    stop_stack
    exit 0
    ;;
  --status)
    show_status
    exit 0
    ;;
  --check-turn)
    python3 "$PROJECT_DIR/engine/turn_check.py"
    exit $?
    ;;
  --install-service|--systemd)
    install_systemd_services
    exit 0
    ;;
  --background|-d)
    MODE="background"
    ;;
  --help|-h)
    sed -n '2,11p' "$0"
    exit 0
    ;;
esac

print_banner

# 0. Warn early if remote (outside-network) video cannot work
if [[ -z "${TURN_URL:-}" && -z "${CF_TURN_KEY_ID:-}" ]] && ! grep -q '"turn_url": "[^"]' "$PROJECT_DIR/data/network_config.json" 2>/dev/null; then
  echo "[WARN] No TURN relay configured: players OUTSIDE your home network will not get video."
  echo "       Set TURN_URL / TURN_USERNAME / TURN_PASSWORD in .env, then run: ./start.sh --check-turn"
fi

# 1. Build or update CyberArena 3D binary if needed
if [[ ! -x "$PROJECT_DIR/engine/test_game/arena3d" ]] || [[ "$PROJECT_DIR/engine/test_game/arena3d.c" -nt "$PROJECT_DIR/engine/test_game/arena3d" ]]; then
  echo "[BUILD] Compiling CyberArena 3D (OpenGL + SDL2)..."
  gcc -O2 "$PROJECT_DIR/engine/test_game/arena3d.c" -o "$PROJECT_DIR/engine/test_game/arena3d" -lSDL2 -lGL -lGLU -lm
  echo "[BUILD] CyberArena 3D compiled."
fi

# 2. Stop any existing instance occupying the port so startup is conflict-free
if pgrep -f "engine/launch_phase6.py" >/dev/null 2>&1; then
  echo "[CLEANUP] Restarting existing Ryoku server instance..."
  pkill -f "engine/launch_phase6.py" 2>/dev/null || true
  sleep 1
fi

LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n 1)
[[ -z "$LAN_IP" ]] && LAN_IP="127.0.0.1"

# 3. Check Cloudflare Tunnel readiness
CRED_FILE=$( awk -F': ' '/credentials-file:/ {print $2}' "$CF_CONFIG" 2>/dev/null | tr -d ' "' || true )
CAN_RUN_TUNNEL=0
if command -v cloudflared >/dev/null 2>&1 && [[ -f "$CF_CONFIG" ]]; then
  if [[ -n "$CRED_FILE" && -f "$CRED_FILE" ]]; then
    CAN_RUN_TUNNEL=1
  elif [[ -f "$HOME/.cloudflared/cert.pem" ]]; then
    echo "[TUNNEL] Auto-generating missing tunnel credentials file: $CRED_FILE"
    mkdir -p "$HOME/.cloudflared"
    if cloudflared tunnel token --cred-file "$CRED_FILE" vansh-cloud-gaming >/dev/null 2>&1; then
      CAN_RUN_TUNNEL=1
    fi
  fi
fi

echo "+----------------------------------------------------------------------------+"
echo "| ACCESS ENDPOINTS                                                           |"
echo "|   Local PC     : http://localhost:${PORT}                                     |"
echo "|   Home Wi-Fi   : http://${LAN_IP}:${PORT}                                  |"
echo "|   Public Web   : https://${PUBLIC_DOMAIN}                       |"
echo "|   Direct Sub   : https://play.vanshdev.online                              |"
echo "|                                                                            |"
echo "| ADMIN CREDENTIALS                                                          |"
echo "|   Username     : ${ADMIN_USER}                                                     |"
echo "|   Password     : ${ADMIN_PASS}                                          |"
echo "+----------------------------------------------------------------------------+"

if [[ "$MODE" == "background" ]]; then
  nohup python3 "$PROJECT_DIR/engine/launch_phase6.py" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --admin-user "$ADMIN_USER" \
    --admin-password "$ADMIN_PASS" \
    --public-domain "$PUBLIC_DOMAIN" \
    > "$LOG_DIR/server.log" 2>&1 &
  SERVER_PID=$!
  echo "[OK] Ryoku Server started in background (PID: $SERVER_PID, Log: data/logs/server.log)"

  if [[ "$CAN_RUN_TUNNEL" -eq 1 ]]; then
    pkill -f "cloudflared.*deploy/cloudflared-config.yml" 2>/dev/null || true
    nohup cloudflared tunnel --config "$CF_CONFIG" run > "$LOG_DIR/tunnel.log" 2>&1 &
    TUNNEL_PID=$!
    echo "[OK] Cloudflare Tunnel started in background (PID: $TUNNEL_PID, Log: data/logs/tunnel.log)"
  else
    echo "[NOTE] Cloudflare Tunnel skipped (credentials file not yet created at $CRED_FILE)."
  fi
  exit 0
fi

# Foreground mode: launch tunnel (if configured) + server, and clean up both on Ctrl+C
TUNNEL_PID=""
cleanup_foreground() {
  echo ""
  echo "[SHUTDOWN] Stopping Ryoku Cloud Gaming stack..."
  if [[ -n "$TUNNEL_PID" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup_foreground INT TERM

if [[ "$CAN_RUN_TUNNEL" -eq 1 ]]; then
  pkill -f "cloudflared.*deploy/cloudflared-config.yml" 2>/dev/null || true
  echo "[TUNNEL] Starting Cloudflare Tunnel (vansh-cloud-gaming)..."
  cloudflared tunnel --config "$CF_CONFIG" run > "$LOG_DIR/tunnel.log" 2>&1 &
  TUNNEL_PID=$!
else
  echo "[NOTE] Running in Local/LAN mode (Cloudflare credentials not found at ${CRED_FILE:-~/.cloudflared})."
fi

echo "[SERVER] Starting Ryoku Cloud Gaming Server on port ${PORT}..."
python3 "$PROJECT_DIR/engine/launch_phase6.py" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --admin-user "$ADMIN_USER" \
  --admin-password "$ADMIN_PASS" \
  --public-domain "$PUBLIC_DOMAIN"


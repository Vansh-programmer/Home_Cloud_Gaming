#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // AUTOSTART & LIFECYCLE CONTROLLER
# ==============================================================================
# Usage:
#   ./autostart.sh [start|stop|restart|status|check-ip]
# Default action: start
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
DOMAIN="play.vanshdev.online"
HEALTH_URL="http://127.0.0.1:80/api/health"

# ANSI Colors
C_RESET="\033[0m"
C_CYAN="\033[1;36m"
C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_DIM="\033[2m"

log_info()    { echo -e "${C_CYAN}[INFO]${C_RESET} $*"; }
log_ok()      { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
log_warn()    { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
log_err()     { echo -e "${C_RED}[ERROR]${C_RESET} $*"; }

check_prerequisites() {
  log_info "Verifying hardware & host requirements..."

  # Docker can start after the lingering user manager during a cold boot.
  if ! docker info >/dev/null 2>&1; then
    log_info "Waiting for Docker to become ready..."
    local attempt=0
    while [[ $attempt -lt 90 ]]; do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
      attempt=$((attempt + 1))
    done
  fi
  if ! docker info >/dev/null 2>&1; then
    log_err "Docker daemon did not become ready within 90 seconds."
    exit 1
  fi

  # 2. Check NVIDIA GPU & driver
  if [[ -f /sys/module/nvidia/version ]]; then
    NV_VER="$(cat /sys/module/nvidia/version | head -n 1)"
    log_ok "NVIDIA GPU driver active (${NV_VER})"
  else
    log_warn "NVIDIA driver not detected in /sys/module/nvidia. Hardware NVENC may be unavailable."
  fi

  # 3. Check virtual controller input devices
  for dev_node in /dev/uinput /dev/uhid; do
    if [[ -e "$dev_node" ]]; then
      log_ok "Virtual device node exists: ${dev_node}"
    else
      log_warn "Device node ${dev_node} not found (may need: sudo modprobe uinput uhid)"
    fi
  done

  # 4. Verify shared games directory
  mkdir -p "$SCRIPT_DIR/data/shared_games"

}

check_ip_and_dns() {
  log_info "Checking public IP and Cloudflare Tunnel..."
  CURRENT_IP=$(curl -s4 --max-time 4 https://api.ipify.org 2>/dev/null || curl -s4 --max-time 4 https://ifconfig.me 2>/dev/null || true)

  if [[ -n "$CURRENT_IP" ]]; then
    log_ok "Current Public IP (Router): ${CURRENT_IP}"
  else
    log_warn "Could not determine public IP (network may be offline)"
    return 0
  fi

  if systemctl is-active --quiet ryoku-cloudflare-tunnel.service; then
    log_ok "Cloudflare Tunnel is active for ${DOMAIN}; WAN IP changes do not require DNS updates."
  else
    log_warn "Cloudflare Tunnel is not active. The public portal may be unreachable."
  fi

  if curl -fsS --max-time 5 "https://${DOMAIN}/api/health" >/dev/null 2>&1; then
    log_ok "Public portal health endpoint is reachable."
  else
    log_warn "Public portal health endpoint is unreachable."
  fi
}

start_services() {
  echo -e "${C_CYAN}========================================================================${C_RESET}"
  echo -e "${C_CYAN}  STARTING RYOKU CLOUD GAMING PLATFORM${C_RESET}"
  echo -e "${C_CYAN}========================================================================${C_RESET}"

  check_prerequisites

  log_info "Starting Docker containers (Wolf + Moonlight Web + access gate + Caddy)..."
  docker compose -f "$COMPOSE_FILE" up -d

  log_info "Waiting for edge gateway health check..."
  local timeout=60
  local elapsed=0
  local healthy=false

  while [[ $elapsed -lt $timeout ]]; do
    if curl -s --max-time 2 "$HEALTH_URL" | grep -q '"ok":true'; then
      healthy=true
      break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  if [[ "$healthy" == true ]]; then
    log_ok "Edge Gateway & Streaming Node are ONLINE!"
  else
    log_err "Gateway health check failed after ${timeout} seconds."
    return 1
  fi

  log_ok "Local account registration is enabled; guests remain blocked from game routes."

  check_ip_and_dns

  echo ""
  echo -e "${C_GREEN}========================================================================${C_RESET}"
  echo -e "${C_GREEN}  PLATFORM SERVICES RUNNING${C_RESET}"
  echo -e "${C_GREEN}========================================================================${C_RESET}"
  echo -e "  Custom Web Portal:     ${C_CYAN}https://${DOMAIN}${C_RESET}"
  echo -e "  Local Portal:          ${C_CYAN}http://localhost${C_RESET}"
  echo -e "  Verified game access:  ${C_CYAN}https://${DOMAIN}${C_RESET}"
  echo -e "  Health Check API:      ${C_CYAN}http://localhost/api/health${C_RESET}"
  echo -e "${C_GREEN}========================================================================${C_RESET}"
}

stop_services() {
  echo -e "${C_YELLOW}Stopping Ryoku Cloud Gaming containers...${C_RESET}"
  docker compose -f "$COMPOSE_FILE" down
  log_ok "All cloud gaming containers stopped."
}

restart_services() {
  stop_services
  sleep 1
  start_services
}

status_services() {
  echo -e "${C_CYAN}========================================================================${C_RESET}"
  echo -e "${C_CYAN}  RYOKU CLOUD GAMING // PLATFORM STATUS${C_RESET}"
  echo -e "${C_CYAN}========================================================================${C_RESET}"
  
  docker compose -f "$COMPOSE_FILE" ps
  echo ""
  
  log_info "Health API response:"
  curl -s --max-time 3 "$HEALTH_URL" || echo "Unreachable"
  echo ""
  echo ""
  
  check_ip_and_dns
}

# Command Router
ACTION="${1:-start}"
case "$ACTION" in
  start)
    start_services
    ;;
  stop)
    stop_services
    ;;
  restart)
    restart_services
    ;;
  status)
    status_services
    ;;
  check-ip)
    check_ip_and_dns
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|status|check-ip]"
    exit 1
    ;;
esac


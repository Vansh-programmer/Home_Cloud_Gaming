#!/usr/bin/env bash
# One-command host setup for Arch Linux and pacman-based derivatives.
# Run from the checked-out project as a normal user:
#   ./deploy/one_click_arch_setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
SYSTEMD_UNIT=/etc/systemd/system/ryoku-cloud-gaming.service

info() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
fail() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[[ "$EUID" -ne 0 ]] || fail "Run this script as your regular login user, not with sudo. It will request sudo when needed."
[[ -n "$RUN_HOME" && -d "$PROJECT_DIR" ]] || fail "Could not determine the project owner or home directory."
[[ "$PROJECT_DIR" != *' '* ]] || fail "Move the project to a path without spaces before installing the systemd service."
[[ -f "$PROJECT_DIR/docker-compose.yml" && -x "$PROJECT_DIR/autostart.sh" ]] || fail "Run this script from a complete Ryoku Cloud Gaming checkout."
[[ -r /etc/os-release ]] || fail "Cannot identify this Linux distribution."

# shellcheck disable=SC1091
source /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *arch*) ;;
  *) fail "This installer supports Arch Linux and pacman-based derivatives only (detected: ${PRETTY_NAME:-unknown})." ;;
esac
command -v pacman >/dev/null 2>&1 || fail "pacman was not found."
command -v sudo >/dev/null 2>&1 || fail "sudo is required to install packages and system services."

info "Preparing the host for $RUN_USER on ${PRETTY_NAME:-Arch Linux}."

packages=(docker docker-compose nvidia-container-toolkit curl)
missing=()
for package in "${packages[@]}"; do
  pacman -Q "$package" >/dev/null 2>&1 || missing+=("$package")
done
if ((${#missing[@]})); then
  info "Installing missing packages and synchronizing the Arch system."
  sudo pacman -Syu --needed "${missing[@]}"
else
  ok "Docker, Compose, NVIDIA Container Toolkit, and curl are installed."
fi

sudo systemctl enable --now docker
if ! sudo docker info >/dev/null 2>&1; then
  fail "The Docker daemon is not responding. Check: sudo systemctl status docker"
fi

# Configure the NVIDIA runtime only when Docker does not already expose it.
runtime_list="$(sudo docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
if [[ "$runtime_list" != *'"nvidia"'* ]]; then
  running_count="$(sudo docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$running_count" != 0 ]]; then
    fail "Docker needs NVIDIA runtime configuration, but containers are running. Stop them during a maintenance window, then rerun this installer; it did not restart Docker."
  fi
  info "Configuring Docker's NVIDIA runtime."
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
else
  ok "Docker already has the NVIDIA runtime configured."
fi

if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
  warn "The NVIDIA driver is not available to this kernel. Install the driver package matching your kernel, reboot, then rerun this script. Driver selection is left to you because Arch derivatives use different kernel and driver packages."
fi

# Wolf needs virtual input devices. Load them now and again on future boots.
sudo modprobe uinput || warn "Could not load uinput; controller support may be unavailable."
sudo modprobe uhid || warn "Could not load uhid; controller support may be unavailable."
printf 'uinput\nuhid\n' | sudo tee /etc/modules-load.d/ryoku-cloud-gaming.conf >/dev/null

# Install upstream Wolf udev rules through a temporary user-owned file.
rule_tmp="$(mktemp)"
trap 'rm -f "$rule_tmp"' EXIT
if curl -fsSL --connect-timeout 10 --max-time 30 \
  https://raw.githubusercontent.com/games-on-whales/wolf/stable/85-wolf.rules \
  -o "$rule_tmp"; then
  sudo install -m 0644 "$rule_tmp" /etc/udev/rules.d/85-wolf.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger
else
  warn "Could not download Wolf's udev rules. Controller access may need manual setup."
fi
rm -f "$rule_tmp"
trap - EXIT

mkdir -p "$PROJECT_DIR/data/shared_games"
sudo docker volume create ryoku-user-storage >/dev/null
sudo docker run --rm -v ryoku-user-storage:/home/retro alpine \
  sh -c 'chmod -R 777 /home/retro'

info "Pulling the platform containers and pinned Steam/Heroic images."
sudo docker compose -f "$PROJECT_DIR/docker-compose.yml" pull
STEAM_DIGEST="sha256:5a2db53cf9ea5d6022b3adb8338a9711c7192225e40f9c61dee5608823dce8fc"
HEROIC_DIGEST="sha256:35f691df044acb051d81bd7a3ecb43e947409a69eeb885d6b84f6fcf14d61824"
sudo docker pull "ghcr.io/games-on-whales/steam@$STEAM_DIGEST"
sudo docker tag "ghcr.io/games-on-whales/steam@$STEAM_DIGEST" ghcr.io/games-on-whales/steam:edge
sudo docker pull "ghcr.io/games-on-whales/heroic-games-launcher@$HEROIC_DIGEST"
sudo docker tag "ghcr.io/games-on-whales/heroic-games-launcher@$HEROIC_DIGEST" ghcr.io/games-on-whales/heroic-games-launcher:edge

# The system unit gets docker as a supplementary group only for this service.
# This works on a fresh host without requiring the user to log out and back in.
unit_tmp="$(mktemp)"
cat >"$unit_tmp" <<EOF
[Unit]
Description=Ryoku Cloud Gaming Platform
Wants=network-online.target docker.service
After=network-online.target docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=180
User=$RUN_USER
SupplementaryGroups=docker
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/autostart.sh start
ExecStop=$PROJECT_DIR/autostart.sh stop
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$unit_tmp" "$SYSTEMD_UNIT"
rm -f "$unit_tmp"
sudo systemctl daemon-reload
sudo systemctl enable ryoku-cloud-gaming.service

# Migrate the previous per-user boot unit without stopping its active process.
# The new system unit supplies the Docker group explicitly and needs no linger.
if systemctl --user is-enabled --quiet ryoku-cloud-gaming.service 2>/dev/null; then
  systemctl --user disable ryoku-cloud-gaming.service
fi

# Avoid recreating running services during setup. On a clean install, let the
# systemd unit perform the initial start and health check.
compose_running="$(sudo docker compose -f "$PROJECT_DIR/docker-compose.yml" ps -q --status running | wc -l | tr -d ' ')"
if [[ "$compose_running" == 0 ]]; then
  info "Starting the game platform."
  sudo systemctl start ryoku-cloud-gaming.service
else
  ok "Existing containers are running; left them untouched. The boot service is enabled for the next start."
fi

ok "Arch-family host setup is complete."
printf '\nLocal portal: http://127.0.0.1\n'
printf 'Service status: sudo systemctl status ryoku-cloud-gaming.service\n'
printf 'Shared game files: %s/data/shared_games (mounted read-only)\n' "$PROJECT_DIR"
if [[ -f "$RUN_HOME/.cloudflared/43a598d8-3099-49ff-8e65-a28b63cafa05.json" ]]; then
  warn "A Cloudflare credential file exists. Public access still needs a matching tunnel service, DNS route, and domain configuration for this host."
else
  warn "Public internet access is not configured. Add a Cloudflare Tunnel credential or configure router port forwarding and DNS; this installer does not create external DNS or tunnel accounts."
fi

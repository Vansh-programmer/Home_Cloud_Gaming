#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$SERVICE_DIR/ryoku-cloud-gaming.service"
USER_NAME="${USER:-$(id -un)}"

if ! command -v systemctl >/dev/null 2>&1 || ! command -v loginctl >/dev/null 2>&1; then
  echo "systemd and loginctl are required for automatic startup." >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/autostart.sh" ]]; then
  echo "The project startup script is missing or not executable: $PROJECT_DIR/autostart.sh" >&2
  exit 1
fi

mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Ryoku Cloud Gaming Platform

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=15
TimeoutStartSec=180
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/autostart.sh start
ExecStop=$PROJECT_DIR/autostart.sh stop
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

if ! loginctl show-user "$USER_NAME" -p Linger 2>/dev/null | grep -qx 'Linger=yes'; then
  loginctl enable-linger "$USER_NAME" || {
    echo "Could not enable user lingering. Run: sudo loginctl enable-linger $USER_NAME" >&2
    exit 1
  }
fi

systemctl --user daemon-reload
systemctl --user enable --now ryoku-cloud-gaming.service
systemctl --user --no-pager --full status ryoku-cloud-gaming.service

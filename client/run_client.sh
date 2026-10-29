#!/usr/bin/env bash
# ==============================================================================
# RYOKU CLOUD GAMING // 1-CLICK NATIVE CLIENT LAUNCHER
# ==============================================================================
set -euo pipefail

CLIENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$CLIENT_DIR/.." && pwd)"

SERVER_URL="${1:-http://localhost:8080}"
TARGET_HOST="${2:-127.0.0.1}"

# Check if Tailscale IP is available
if command -v tailscale >/dev/null 2>&1; then
  TS_IP=$(tailscale ip -4 2>/dev/null || true)
  if [[ -n "$TS_IP" && "$TARGET_HOST" == "127.0.0.1" ]]; then
    TARGET_HOST="$TS_IP"
  fi
fi

echo "[RYOKU CLIENT] Starting native desktop client..."
echo "  Server URL  : $SERVER_URL"
echo "  Moonlight Target: $TARGET_HOST"

exec python3 "$CLIENT_DIR/ryoku_client.py" --server "$SERVER_URL" --host "$TARGET_HOST"


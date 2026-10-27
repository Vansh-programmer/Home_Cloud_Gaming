#!/usr/bin/env python3
"""
Phase 6 Production Launcher: Full Cloud Gaming Platform with External HTTPS Access,
STUN/TURN NAT Traversal, and Always-On PC-Offline Status Support.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import CloudGamingDatabase  # noqa: E402
from backend.network_manager import NetworkConfigManager  # noqa: E402
from backend.orchestrator import SessionOrchestrator  # noqa: E402
from backend.server import create_orchestrator_app  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.storage_manager import UserStorageManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("launch_phase6")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ryoku Cloud Gaming - Full Production Server (Phase 6)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP/WebSocket port (default: 8080)")
    parser.add_argument("--data-root", default="", help="Custom data directory root (default: ./data)")
    parser.add_argument(
        "--admin-user",
        default=os.environ.get("ADMIN_USERNAME", "vansh"),
        help="Bootstrap admin username (default: vansh)",
    )
    parser.add_argument(
        "--admin-password",
        default=os.environ.get("ADMIN_PASSWORD", "ryoku-admin-2026"),
        help="Bootstrap admin password on first run (default: ryoku-admin-2026)",
    )
    parser.add_argument(
        "--public-domain",
        default="",
        help="Optional public HTTPS domain (e.g. play.yourdomain.com)",
    )
    parser.add_argument(
        "--stun-url",
        default="",
        help="Optional STUN server URL (default: stun:stun.l.google.com:19302)",
    )
    parser.add_argument(
        "--turn-url",
        default="",
        help="Optional TURN server URL (e.g. turn:turn.yourdomain.com:3478)",
    )
    parser.add_argument(
        "--turn-secret",
        default="",
        help="Optional coturn HMAC-SHA1 shared secret for ephemeral TURN REST credentials",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=600.0,
        help="Idle timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--disconnect-grace",
        type=float,
        default=300.0,
        help="Browser disconnect grace period in seconds (default: 300)",
    )
    parser.add_argument(
        "--create-invite",
        action="store_true",
        help="Generate a single-use invite code and exit",
    )
    parser.add_argument("--invite-note", default="", help="Optional note for --create-invite")
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=int(os.environ.get("MAX_CONCURRENT_SESSIONS", "4")),
        help="Maximum concurrent gaming sessions (multiplayer LAN slots, default: 4)",
    )
    parser.add_argument(
        "--allow-pre-sandboxed",
        action="store_true",
        help="Allow running inside an already-sandboxed test environment",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve() if args.data_root else (PROJECT_ROOT / "data")
    storage_mgr = UserStorageManager(data_root=data_root)
    storage_mgr.ensure_base_directories()
    steam_mgr = SteamLibraryManager(storage_mgr.shared_steam_dir)
    network_mgr = NetworkConfigManager(data_root=data_root)

    net_updates = {}
    if args.public_domain:
        net_updates["public_domain"] = args.public_domain
    if args.stun_url:
        net_updates["stun_url"] = args.stun_url
    if args.turn_url:
        net_updates["turn_url"] = args.turn_url
    if args.turn_secret:
        net_updates["turn_secret"] = args.turn_secret
    if net_updates:
        network_mgr.update_config(net_updates)

    db = CloudGamingDatabase(db_path=data_root / "cloud_gaming.db")
    if db.ensure_bootstrap_admin(username=args.admin_user, password=args.admin_password):
        storage_mgr.prepare_user_storage(args.admin_user)
        logger.info("Created bootstrap admin account '%s'", args.admin_user)

    if args.create_invite:
        inv = db.create_invite(created_by=args.admin_user, note=args.invite_note)
        print(json.dumps(inv, indent=2))
        return 0

    orchestrator = SessionOrchestrator(
        db=db,
        storage_mgr=storage_mgr,
        steam_mgr=steam_mgr,
        idle_timeout_sec=args.idle_timeout,
        disconnect_grace_sec=args.disconnect_grace,
        allow_pre_sandboxed=args.allow_pre_sandboxed,
        network_mgr=network_mgr,
        max_concurrent_sessions=args.max_sessions,
    )

    app = create_orchestrator_app(
        db=db,
        storage_mgr=storage_mgr,
        steam_mgr=steam_mgr,
        orchestrator=orchestrator,
    )

    # Cloudflare Tunnel Auto-Supervision
    cf_proc = None
    cf_config = PROJECT_ROOT / "deploy" / "cloudflared-config.yml"
    disable_tunnel = os.environ.get("DISABLE_AUTO_TUNNEL", "0").strip() == "1"
    if not disable_tunnel and cf_config.exists() and shutil.which("cloudflared"):
        if not network_mgr._is_process_running("cloudflared"):
            cred_file = None
            try:
                for line in cf_config.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("credentials-file:"):
                        cred_file = Path(line.split(":", 1)[1].strip().strip('"').strip("'"))
                        break
            except Exception:
                pass
            if cred_file and cred_file.exists():
                logger.info("Auto-starting Cloudflare Tunnel daemon for vansh-cloud-gaming...")
                log_dir = data_root / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                tunnel_log = log_dir / "tunnel.log"
                try:
                    tunnel_log.unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    tfh = open(tunnel_log, "a", encoding="utf-8")
                    cf_proc = subprocess.Popen(
                        ["cloudflared", "tunnel", "--config", str(cf_config), "run"],
                        stdout=tfh,
                        stderr=subprocess.STDOUT,
                    )
                    tfh.close()
                    logger.info("Cloudflare Tunnel running (PID: %d, log: %s)", cf_proc.pid, tunnel_log)
                except Exception as exc:
                    logger.warning("Could not auto-start cloudflared: %s", exc)

    async def _cleanup_tunnel(_app: web.Application) -> None:
        if cf_proc and cf_proc.poll() is None:
            logger.info("Terminating auto-managed cloudflared tunnel...")
            cf_proc.terminate()
            try:
                cf_proc.wait(timeout=2)
            except Exception:
                cf_proc.kill()

    app.on_cleanup.append(_cleanup_tunnel)

    logger.info(
        "Ryoku Cloud Gaming Server listening on http://%s:%d (domain=%s)",
        args.host,
        args.port,
        network_mgr.public_domain or "localhost",
    )
    web.run_app(app, host=args.host, port=args.port, print=None, access_log=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())


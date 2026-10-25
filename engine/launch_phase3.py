#!/usr/bin/env python3
"""
Phase 3 Launcher: Backend Orchestrator, Safety Limits & Invite-Only Auth Server.

Features:
- Initializes SQLite database (data/cloud_gaming.db) and bootstrap admin account.
- Enforces invite-only login (no public registration without an admin invite code).
- Enforces the 1-session-at-a-time GPU lock across the PC ("Gaming PC in use by <user>").
- Manages the Session State Machine (starting -> ready -> playing -> ended).
- Enforces configurable idle timeout and browser-disconnect reconnect grace window.
- Provides Admin APIs for live GPU telemetry, force-ending sessions, and managing users/invites.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import CloudGamingDatabase  # noqa: E402
from backend.orchestrator import SessionOrchestrator  # noqa: E402
from backend.server import create_orchestrator_app  # noqa: E402
from engine.steam_manager import SteamLibraryManager  # noqa: E402
from engine.storage_manager import UserStorageManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("launch_phase3")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ryoku Cloud Gaming - Phase 3 Backend Orchestrator")
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
        "--idle-timeout",
        type=float,
        default=600.0,
        help="Idle timeout in seconds before auto-ending an inactive session (default: 600)",
    )
    parser.add_argument(
        "--disconnect-grace",
        type=float,
        default=300.0,
        help="Grace period in seconds to keep a session alive when the browser disconnects (default: 300)",
    )
    parser.add_argument(
        "--create-invite",
        action="store_true",
        help="Generate a new single-use invite code from CLI and exit",
    )
    parser.add_argument(
        "--invite-note",
        default="",
        help="Optional note when generating an invite code via --create-invite",
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

    db_path = data_root / "cloud_gaming.db"
    db = CloudGamingDatabase(db_path=db_path)
    created_admin = db.ensure_bootstrap_admin(
        username=args.admin_user,
        password=args.admin_password,
    )
    if created_admin:
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
    )

    app = create_orchestrator_app(
        db=db,
        storage_mgr=storage_mgr,
        steam_mgr=steam_mgr,
        orchestrator=orchestrator,
    )

    logger.info(
        "Ryoku Cloud Gaming Orchestrator listening on http://%s:%d (idle_timeout=%.0fs, disconnect_grace=%.0fs)",
        args.host,
        args.port,
        args.idle_timeout,
        args.disconnect_grace,
    )
    web.run_app(app, host=args.host, port=args.port, print=None, access_log=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())


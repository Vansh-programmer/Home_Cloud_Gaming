#!/usr/bin/env python3
"""
Phase 2 Launcher: Isolated Steam & Per-User Persistent Storage Session Launcher.

Usage examples:
  # List discovered Steam games and built-in apps:
  python3 engine/launch_phase2.py --list-games

  # Launch CyberArena 3D for user 'alice' (persists saves in data/users/alice):
  python3 engine/launch_phase2.py --user alice --app-id 0 --port 8080

  # Launch Steam Big Picture / Account Login for user 'alice' inside isolated container:
  python3 engine/launch_phase2.py --user alice --app-id 7 --port 8080

  # Launch a specific Steam AppID for user 'alice':
  python3 engine/launch_phase2.py --user alice --app-id 620 --port 8080

  # Inspect persistent save & Steam login token status for user 'alice':
  python3 engine/launch_phase2.py --user alice --user-status
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.launch_phase1 import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())


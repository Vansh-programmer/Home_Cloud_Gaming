"""
SQLite Database & Invite-Only Authentication Store (Phase 3).

Security invariants:
1. Invite-only accounts: Public sign-up without a valid, unrevoked, unexpired invite code is impossible.
2. Passwords are salted with 16 cryptographic random bytes and hashed with PBKDF2-HMAC-SHA256 (200,000 iterations)
   and verified using constant-time hmac.compare_digest().
3. Session tokens are 256-bit cryptographic random values; only their SHA-256 digest is stored in SQLite.
4. The SQLite database file lives in data/cloud_gaming.db on the host and is NEVER mounted inside
   any game session container.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from engine.storage_manager import validate_user_id

PBKDF2_ITERATIONS = 200_000
DEFAULT_TOKEN_TTL_SEC = 7 * 24 * 3600  # 7 days
DEFAULT_INVITE_TTL_SEC = 7 * 24 * 3600  # 7 days


def hash_password(password: str) -> str:
    """Hash a password with a random 16-byte salt using PBKDF2-HMAC-SHA256."""
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a password against its stored PBKDF2 hash."""
    try:
        algo, iter_str, salt_hex, dk_hex = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        actual_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual_dk, expected_dk)
    except Exception:
        return False


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class CloudGamingDatabase:
    """Manages SQLite persistence for users, invite codes, auth tokens, and session history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'player',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_login_at REAL
                );

                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'player',
                    created_by TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    used_by TEXT,
                    created_at REAL NOT NULL,
                    used_at REAL,
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    user_agent TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS session_history (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    game_title TEXT NOT NULL,
                    quality TEXT NOT NULL DEFAULT 'high',
                    state TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    duration_sec REAL,
                    end_reason TEXT
                );
                """
            )

    def ensure_bootstrap_admin(self, username: str = "vansh", password: str = "ryoku-admin-2026") -> bool:
        """
        Ensure at least one admin account exists on first boot.
        Returns True if the bootstrap admin was newly created, False if an admin already existed.
        """
        clean_user = validate_user_id(username)
        with self._connect() as conn:
            row = conn.execute("SELECT username FROM users WHERE role = 'admin' LIMIT 1").fetchone()
            if row is not None:
                return False
            now = time.time()
            pw_hash = hash_password(password)
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, active, created_at)
                VALUES (?, ?, 'admin', 1, ?)
                """,
                (clean_user, pw_hash, now),
            )
            return True

    # -------------------------------------------------------------------------
    # User & Invite Management
    # -------------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "player",
    ) -> Dict[str, object]:
        clean_user = validate_user_id(username)
        if role not in ("admin", "player"):
            raise ValueError("Invalid role; must be 'admin' or 'player'.")
        pw_hash = hash_password(password)
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT username FROM users WHERE username = ?", (clean_user,)
            ).fetchone()
            if existing:
                raise ValueError(f"User '{clean_user}' already exists.")
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (clean_user, pw_hash, role, now),
            )
        return {
            "username": clean_user,
            "role": role,
            "active": True,
            "created_at": now,
            "last_login_at": None,
        }

    def delete_user(self, username: str) -> bool:
        clean_user = validate_user_id(username)
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE username = ?", (clean_user,))
            cur = conn.execute("DELETE FROM users WHERE username = ?", (clean_user,))
            return cur.rowcount > 0

    def set_user_active(self, username: str, active: bool) -> bool:
        clean_user = validate_user_id(username)
        with self._connect() as conn:
            if not active:
                conn.execute("DELETE FROM auth_tokens WHERE username = ?", (clean_user,))
            cur = conn.execute(
                "UPDATE users SET active = ? WHERE username = ?",
                (1 if active else 0, clean_user),
            )
            return cur.rowcount > 0

    def get_user(self, username: str) -> Optional[Dict[str, object]]:
        try:
            clean_user = validate_user_id(username)
        except ValueError:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, role, active, created_at, last_login_at FROM users WHERE username = ?",
                (clean_user,),
            ).fetchone()
            if not row:
                return None
            return {
                "username": row["username"],
                "role": row["role"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
                "last_login_at": row["last_login_at"],
            }

    def list_users(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, role, active, created_at, last_login_at FROM users ORDER BY created_at ASC"
            ).fetchall()
            return [
                {
                    "username": r["username"],
                    "role": r["role"],
                    "active": bool(r["active"]),
                    "created_at": r["created_at"],
                    "last_login_at": r["last_login_at"],
                }
                for r in rows
            ]

    def create_invite(
        self,
        created_by: str,
        note: str = "",
        role: str = "player",
        ttl_sec: int = DEFAULT_INVITE_TTL_SEC,
    ) -> Dict[str, object]:
        if role not in ("admin", "player"):
            raise ValueError("Invalid role.")
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(3).upper()
        code = f"RYOKU-{part1}-{part2}"
        now = time.time()
        expires_at = now + max(60, ttl_sec)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO invites (code, role, created_by, note, created_at, expires_at, revoked)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (code, role, created_by, note.strip()[:120], now, expires_at),
            )
        return {
            "code": code,
            "role": role,
            "created_by": created_by,
            "note": note.strip()[:120],
            "used_by": None,
            "created_at": now,
            "used_at": None,
            "expires_at": expires_at,
            "revoked": False,
        }

    def redeem_invite(self, code: str, username: str, password: str) -> Dict[str, object]:
        """
        Validate a single-use invite code and create the user account atomically.
        Raises ValueError if the invite code is missing, invalid, used, revoked, or expired.
        """
        clean_code = code.strip().upper()
        if not clean_code:
            raise ValueError("An invite code is required. Public sign-up is disabled.")
        clean_user = validate_user_id(username)
        pw_hash = hash_password(password)
        now = time.time()

        with self._connect() as conn:
            inv = conn.execute(
                "SELECT * FROM invites WHERE code = ?", (clean_code,)
            ).fetchone()
            if not inv:
                raise ValueError("Invalid invite code.")
            if inv["revoked"]:
                raise ValueError("This invite code has been revoked.")
            if inv["used_by"] is not None:
                raise ValueError("This invite code has already been used.")
            if now > inv["expires_at"]:
                raise ValueError("This invite code has expired.")

            existing = conn.execute(
                "SELECT username FROM users WHERE username = ?", (clean_user,)
            ).fetchone()
            if existing:
                raise ValueError(f"Username '{clean_user}' is already taken.")

            role = inv["role"]
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, active, created_at, last_login_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (clean_user, pw_hash, role, now, now),
            )
            conn.execute(
                """
                UPDATE invites SET used_by = ?, used_at = ? WHERE code = ?
                """,
                (clean_user, now, clean_code),
            )

        return {
            "username": clean_user,
            "role": role,
            "active": True,
            "created_at": now,
            "last_login_at": now,
        }

    def revoke_invite(self, code: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE invites SET revoked = 1 WHERE code = ? AND used_by IS NULL",
                (code.strip().upper(),),
            )
            return cur.rowcount > 0

    def list_invites(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM invites ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            return [
                {
                    "code": r["code"],
                    "role": r["role"],
                    "created_by": r["created_by"],
                    "note": r["note"],
                    "used_by": r["used_by"],
                    "created_at": r["created_at"],
                    "used_at": r["used_at"],
                    "expires_at": r["expires_at"],
                    "revoked": bool(r["revoked"]),
                }
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Authentication & Session Tokens
    # -------------------------------------------------------------------------

    def authenticate_user(
        self,
        username: str,
        password: str,
        user_agent: str = "",
        ip_address: str = "",
        ttl_sec: int = DEFAULT_TOKEN_TTL_SEC,
    ) -> Optional[Dict[str, object]]:
        """
        Verify username & password; if valid and active, issue a new session token.
        """
        try:
            clean_user = validate_user_id(username)
        except ValueError:
            return None

        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, active FROM users WHERE username = ?",
                (clean_user,),
            ).fetchone()
            if not row or not row["active"]:
                return None
            if not verify_password(password, row["password_hash"]):
                return None

            raw_token = secrets.token_urlsafe(32)
            token_hash = _hash_token(raw_token)
            expires_at = now + ttl_sec

            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE username = ?",
                (now, clean_user),
            )
            conn.execute(
                """
                INSERT INTO auth_tokens (token_hash, username, created_at, expires_at, user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_hash, clean_user, now, expires_at, user_agent[:200], ip_address[:64]),
            )

        return {
            "token": raw_token,
            "username": row["username"],
            "role": row["role"],
            "expires_at": expires_at,
        }

    def issue_token_for_user(
        self,
        username: str,
        user_agent: str = "",
        ip_address: str = "",
        ttl_sec: int = DEFAULT_TOKEN_TTL_SEC,
    ) -> Dict[str, object]:
        clean_user = validate_user_id(username)
        now = time.time()
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        expires_at = now + ttl_sec
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, role FROM users WHERE username = ? AND active = 1",
                (clean_user,),
            ).fetchone()
            if not row:
                raise ValueError("User not found or inactive.")
            conn.execute(
                """
                INSERT INTO auth_tokens (token_hash, username, created_at, expires_at, user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_hash, clean_user, now, expires_at, user_agent[:200], ip_address[:64]),
            )
        return {
            "token": raw_token,
            "username": row["username"],
            "role": row["role"],
            "expires_at": expires_at,
        }

    def verify_session_token(self, raw_token: str) -> Optional[Dict[str, object]]:
        if not raw_token or len(raw_token) < 16:
            return None
        token_hash = _hash_token(raw_token)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT t.username, t.expires_at, u.role, u.active
                FROM auth_tokens t
                JOIN users u ON u.username = t.username
                WHERE t.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if not row["active"] or now > row["expires_at"]:
                conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
                return None
            return {
                "username": row["username"],
                "role": row["role"],
                "expires_at": row["expires_at"],
            }

    def revoke_session_token(self, raw_token: str) -> bool:
        if not raw_token:
            return False
        token_hash = _hash_token(raw_token)
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Session History Audit Log
    # -------------------------------------------------------------------------

    def record_session_start(
        self,
        session_id: str,
        username: str,
        app_id: str,
        game_title: str,
        quality: str = "high",
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_history
                (session_id, username, app_id, game_title, quality, state, started_at)
                VALUES (?, ?, ?, ?, ?, 'starting', ?)
                """,
                (session_id, username, str(app_id), game_title, quality, now),
            )

    def update_session_state(self, session_id: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE session_history SET state = ? WHERE session_id = ?",
                (state, session_id),
            )

    def record_session_end(
        self,
        session_id: str,
        end_reason: str,
        started_at: Optional[float] = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            if started_at is None:
                row = conn.execute(
                    "SELECT started_at FROM session_history WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                started_at = float(row["started_at"]) if row else now
            duration = round(max(0.0, now - started_at), 1)
            conn.execute(
                """
                UPDATE session_history
                SET state = 'ended', ended_at = ?, duration_sec = ?, end_reason = ?
                WHERE session_id = ?
                """,
                (now, duration, end_reason, session_id),
            )

    def list_session_history(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM session_history ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "session_id": r["session_id"],
                    "username": r["username"],
                    "app_id": r["app_id"],
                    "game_title": r["game_title"],
                    "quality": r["quality"],
                    "state": r["state"],
                    "started_at": r["started_at"],
                    "ended_at": r["ended_at"],
                    "duration_sec": r["duration_sec"],
                    "end_reason": r["end_reason"],
                }
                for r in rows
            ]

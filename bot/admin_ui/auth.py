"""
Admin authentication for the admin UI.

Handles admin-login.json load/save, password hashing (passlib/bcrypt),
first-time setup, pending admin usernames, and session validation.

Session store notes:
- Sessions are held in-process memory and do NOT survive bot restarts.
- All active admin sessions are invalidated whenever the bot process stops.
- Sessions expire after SESSION_TTL_SECONDS (24 hours) of inactivity.
- The session dict is pruned of expired entries whenever a new session is created
  to prevent unbounded memory growth in long-running processes.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

import bcrypt

logger = logging.getLogger("monolithbot.admin_ui")

# Session store: token -> { "username": str, "expiry": float }
# NOTE: In-memory only — all sessions are lost on process restart.
_sessions: dict[str, dict[str, Any]] = {}
SESSION_COOKIE_NAME = "admin_session"
SESSION_TTL_SECONDS = 24 * 3600  # 24 hours
_MAX_SESSIONS = 200  # Prune threshold to cap memory usage


def _hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with cost factor 12.

    Args:
        password: The plaintext password to hash.

    Returns:
        A bcrypt hash string safe for storage.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def _verify_password(password: str, hash_str: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Args:
        password: The plaintext password to check.
        hash_str: The bcrypt hash string retrieved from storage.

    Returns:
        True if the password matches the hash, False otherwise.
        Also returns False if the hash is malformed (logs a warning).
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))
    except ValueError:
        # Malformed hash in the login file — log and treat as no-match.
        logger.warning("Malformed password hash encountered during verification")
        return False


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning an empty dict on missing file or parse error.

    Args:
        path: Filesystem path to the JSON file.

    Returns:
        Parsed dict, or {} if the file does not exist or cannot be parsed.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not load admin login file {path}: {e}")
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to path as JSON, then restrict file permissions.

    Uses a write-to-temp-then-rename pattern so the target file is never
    left in a partially-written state if the process is interrupted.

    The resulting file is chmod'd to 0o600 (owner read/write only) to
    protect credentials stored inside.

    Args:
        path: Destination path for the JSON file.
        data: Dictionary to serialise.

    Raises:
        OSError: If the write or rename fails. The temp file is cleaned up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
        os.chmod(path, 0o600)
    except OSError:
        logger.exception("Failed to save admin login file to %s", path)
        tmp.unlink(missing_ok=True)
        raise


def auth_file_exists(login_file_path: str) -> bool:
    """Check whether the admin login credentials file exists on disk.

    Args:
        login_file_path: Filesystem path to the admin-login.json file.

    Returns:
        True if the file exists, False otherwise. Does not validate contents.
    """
    return Path(login_file_path).exists()


def _prune_expired_sessions() -> None:
    """Remove all expired sessions from the in-memory store.

    Called automatically by create_session when the session count reaches
    _MAX_SESSIONS to prevent unbounded memory growth.
    """
    now = time.time()
    expired = [token for token, s in _sessions.items() if now > s["expiry"]]
    for token in expired:
        del _sessions[token]


def first_login_setup(login_file_path: str, username: str, password: str) -> bool:
    """
    Create admin-login.json with the first admin when file does not exist.
    Returns True if file was created, False if file already exists.
    """
    path = Path(login_file_path)
    if path.exists():
        return False
    data = {
        "initial_admin": {
            "username": username.strip(),
            "password_hash": _hash_password(password),
        },
        "admins": [],
        "pending_usernames": [],
    }
    _save_json(path, data)
    logger.info(f"Admin UI: created initial admin file for user {username!r}")
    return True


def verify_login(login_file_path: str, username: str, password: str) -> Optional[str]:
    """
    Verify username/password. If valid, return the canonical username (for session).
    If username is in pending_usernames, accept any password, save it as their
    password, move them to admins, and return username.
    Returns None if invalid.
    """
    path = Path(login_file_path)
    data = _load_json(path)
    if not data:
        return None

    raw_username = username.strip()
    if not raw_username or not password:
        return None

    # Check pending first: first login with this username sets their password.
    # Enforce a minimum password length at claim time to prevent trivially weak
    # admin passwords being set via the first-login flow.
    pending = data.get("pending_usernames", [])
    if isinstance(pending, list) and raw_username in pending:
        if len(password) < 12:
            # Don't save anything — return None so the login page shows an error.
            logger.warning(
                "Admin UI: pending admin %r supplied a password shorter than 12 characters",
                raw_username,
            )
            return None
        data["pending_usernames"] = [u for u in pending if u != raw_username]
        data.setdefault("admins", [])
        if not isinstance(data["admins"], list):
            data["admins"] = []
        data["admins"].append(
            {
                "username": raw_username,
                "password_hash": _hash_password(password),
            }
        )
        _save_json(path, data)
        logger.info(f"Admin UI: new admin claimed account {raw_username!r}")
        return raw_username

    # Initial admin
    initial = data.get("initial_admin")
    if isinstance(initial, dict):
        u = initial.get("username")
        if (
            u
            and u == raw_username
            and _verify_password(password, initial.get("password_hash", ""))
        ):
            return raw_username

    # Other admins
    for adm in data.get("admins", []):
        if isinstance(adm, dict) and adm.get("username") == raw_username:
            if _verify_password(password, adm.get("password_hash", "")):
                return raw_username
            break

    return None


def is_initial_admin(login_file_path: str, username: str) -> bool:
    """Check whether the given username is the initial (bootstrap) admin.

    The initial admin is the one whose credentials were set up on first login.
    Only the initial admin can add new pending admin accounts.

    Args:
        login_file_path: Filesystem path to the admin-login.json file.
        username: The username to check.

    Returns:
        True if username matches the initial_admin entry, False otherwise.
    """
    path = Path(login_file_path)
    data = _load_json(path)
    initial = data.get("initial_admin")
    if isinstance(initial, dict):
        return initial.get("username") == username
    return False


def add_pending_admin(
    login_file_path: str, username: str, by_username: str
) -> tuple[bool, str]:
    """
    Add a username to pending_usernames. Only the initial admin can do this.
    Returns (success, message).
    """
    path = Path(login_file_path)
    data = _load_json(path)
    initial = data.get("initial_admin")
    if not isinstance(initial, dict) or initial.get("username") != by_username:
        return False, "Only the initial admin can add new admins."

    raw = username.strip()
    if not raw:
        return False, "Username cannot be empty."

    # Disallow duplicate
    pending = data.get("pending_usernames", [])
    if not isinstance(pending, list):
        pending = []
    if raw in pending:
        return False, "That username is already in the pending list."
    if raw == initial.get("username"):
        return False, "Cannot add the initial admin again."
    for adm in data.get("admins", []):
        if isinstance(adm, dict) and adm.get("username") == raw:
            return False, "That user is already an admin."

    pending.append(raw)
    data["pending_usernames"] = pending
    _save_json(path, data)
    return True, f"Added {raw!r}. They can log in once to set their password."


def create_session(username: str) -> str:
    """Create a new authenticated session for the given admin username.

    Prunes expired sessions first when the store exceeds _MAX_SESSIONS to
    prevent unbounded memory growth in long-running processes.

    Args:
        username: The canonical admin username to associate with the session.

    Returns:
        A URL-safe random token string that the client stores as a cookie.
    """
    if len(_sessions) >= _MAX_SESSIONS:
        _prune_expired_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "expiry": time.time() + SESSION_TTL_SECONDS,
    }
    return token


def get_session(token: Optional[str]) -> Optional[str]:
    """Validate a session token and return the associated username.

    Expired sessions are removed from the store on first access.

    Args:
        token: The session token from the browser cookie. May be None.

    Returns:
        The admin username if the token is valid and not expired, else None.
    """
    if not token:
        return None
    s = _sessions.get(token)
    if not s or time.time() > s["expiry"]:
        if token in _sessions:
            del _sessions[token]
        return None
    return s["username"]


def drop_session(token: Optional[str]) -> None:
    """Invalidate a session token, effectively logging the admin out.

    Args:
        token: The session token to remove. No-op if None or already gone.
    """
    if token and token in _sessions:
        del _sessions[token]

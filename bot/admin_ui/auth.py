"""
Admin authentication for the admin UI.

Handles admin-login.json load/save, password hashing (passlib/bcrypt),
first-time setup, pending admin usernames, and session validation.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Optional

import bcrypt

logger = logging.getLogger("monolithbot.admin_ui")

# Session store: token -> { "username": str, "expiry": float }
_sessions: dict[str, dict[str, Any]] = {}
SESSION_COOKIE_NAME = "admin_session"
SESSION_TTL_SECONDS = 24 * 3600  # 24 hours


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def _verify_password(password: str, hash_str: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))
    except Exception:
        return False


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not load admin login file {path}: {e}")
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def auth_file_exists(login_file_path: str) -> bool:
    return Path(login_file_path).exists()


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

    # Check pending first: first login with this username sets their password
    pending = data.get("pending_usernames", [])
    if isinstance(pending, list) and raw_username in pending:
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
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "expiry": time.time() + SESSION_TTL_SECONDS,
    }
    return token


def get_session(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    s = _sessions.get(token)
    if not s or time.time() > s["expiry"]:
        if token in _sessions:
            del _sessions[token]
        return None
    return s["username"]


def drop_session(token: Optional[str]) -> None:
    if token and token in _sessions:
        del _sessions[token]

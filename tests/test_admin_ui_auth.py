"""
Tests for bot.admin_ui.auth.

Covers admin-login.json first-time setup, verify_login, pending admins,
sessions, and add_pending_admin.
"""

from __future__ import annotations

import time
from pathlib import Path

from bot.admin_ui import auth


# -----------------------------------------------------------------------------
# auth_file_exists
# -----------------------------------------------------------------------------


class TestAuthFileExists:
    def test_returns_false_when_file_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert auth.auth_file_exists(str(path)) is False

    def test_returns_true_when_file_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "exists.json"
        path.touch()
        assert auth.auth_file_exists(str(path)) is True


# -----------------------------------------------------------------------------
# first_login_setup
# -----------------------------------------------------------------------------


class TestFirstLoginSetup:
    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        assert not path.exists()
        out = auth.first_login_setup(str(path), "admin", "secret123")
        assert out is True
        assert path.exists()
        import json

        data = json.loads(path.read_text())
        assert data["initial_admin"]["username"] == "admin"
        assert "password_hash" in data["initial_admin"]
        assert data["admins"] == []
        assert data["pending_usernames"] == []

    def test_returns_false_when_file_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "first", "pass1")
        out = auth.first_login_setup(str(path), "second", "pass2")
        assert out is False
        data = __import__("json").loads(path.read_text())
        assert data["initial_admin"]["username"] == "first"

    def test_strips_username(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "  u  ", "p")
        data = __import__("json").loads(path.read_text())
        assert data["initial_admin"]["username"] == "u"


# -----------------------------------------------------------------------------
# verify_login
# -----------------------------------------------------------------------------


class TestVerifyLogin:
    def test_returns_username_when_valid(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "admin", "secret")
        assert auth.verify_login(str(path), "admin", "secret") == "admin"

    def test_returns_none_when_wrong_password(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "admin", "secret")
        assert auth.verify_login(str(path), "admin", "wrong") is None

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert auth.verify_login(str(path), "admin", "secret") is None

    def test_returns_none_when_empty_username_or_password(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "admin", "secret")
        assert auth.verify_login(str(path), "", "secret") is None
        assert auth.verify_login(str(path), "admin", "") is None

    def test_pending_username_claims_and_returns(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass0")
        ok, _ = auth.add_pending_admin(str(path), "newadmin", "initial")
        assert ok is True
        assert auth.verify_login(str(path), "newadmin", "anypassword") == "newadmin"
        data = __import__("json").loads(path.read_text())
        assert "newadmin" not in data.get("pending_usernames", [])
        assert any(a.get("username") == "newadmin" for a in data.get("admins", []))


# -----------------------------------------------------------------------------
# is_initial_admin
# -----------------------------------------------------------------------------


class TestIsInitialAdmin:
    def test_true_for_initial_admin(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        assert auth.is_initial_admin(str(path), "initial") is True

    def test_false_for_other(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        assert auth.is_initial_admin(str(path), "other") is False

    def test_false_when_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert auth.is_initial_admin(str(path), "any") is False


# -----------------------------------------------------------------------------
# add_pending_admin
# -----------------------------------------------------------------------------


class TestAddPendingAdmin:
    def test_initial_admin_can_add(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        ok, msg = auth.add_pending_admin(str(path), "newuser", "initial")
        assert ok is True
        assert "newuser" in msg
        data = __import__("json").loads(path.read_text())
        assert "newuser" in data["pending_usernames"]

    def test_non_initial_cannot_add(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        ok, msg = auth.add_pending_admin(str(path), "newuser", "other")
        assert ok is False
        assert "initial admin" in msg

    def test_rejects_empty_username(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        ok, msg = auth.add_pending_admin(str(path), "  ", "initial")
        assert ok is False
        assert "empty" in msg.lower()

    def test_rejects_duplicate_pending(self, tmp_path: Path) -> None:
        path = tmp_path / "admin.json"
        auth.first_login_setup(str(path), "initial", "pass")
        auth.add_pending_admin(str(path), "u", "initial")
        ok, msg = auth.add_pending_admin(str(path), "u", "initial")
        assert ok is False
        assert "already" in msg.lower()


# -----------------------------------------------------------------------------
# create_session / get_session / drop_session
# -----------------------------------------------------------------------------


class TestSession:
    def test_create_and_get_session(self) -> None:
        token = auth.create_session("user1")
        assert token
        assert auth.get_session(token) == "user1"

    def test_get_session_none_for_invalid_token(self) -> None:
        assert auth.get_session(None) is None
        assert auth.get_session("nonexistent") is None

    def test_drop_session_removes_token(self) -> None:
        token = auth.create_session("user1")
        auth.drop_session(token)
        assert auth.get_session(token) is None

    def test_expired_session_returns_none(self) -> None:
        token = auth.create_session("user1")
        # Force expiry by mutating internal store
        auth._sessions[token]["expiry"] = time.time() - 1
        assert auth.get_session(token) is None

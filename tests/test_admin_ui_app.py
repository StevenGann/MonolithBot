"""
Tests for bot.admin_ui.app.

Covers create_app, index, login, logout, and dashboard routes using aiohttp TestClient.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.admin_ui.app import create_app
from bot.admin_ui import auth


# -----------------------------------------------------------------------------
# create_app
# -----------------------------------------------------------------------------


class TestCreateApp:
    def test_returns_application(self) -> None:
        app = create_app()
        assert app is not None
        assert app.get("bot") is None
        assert app.get("config") is None

    def test_stores_bot_and_config_when_provided(self) -> None:
        bot = MagicMock()
        config = MagicMock()
        app = create_app(bot=bot, config=config)
        assert app.get("bot") is bot
        assert app.get("config") is config


# -----------------------------------------------------------------------------
# Routes (aiohttp TestClient)
# -----------------------------------------------------------------------------


@pytest.fixture
def login_file_path(tmp_path: Path) -> str:
    return str(tmp_path / "admin-login.json")


@pytest.fixture
def app_with_config(login_file_path: str):
    """App with config that points to a temp admin login file."""
    config = MagicMock()
    config.admin_ui = MagicMock()
    config.admin_ui.admin_login_file = login_file_path
    return create_app(bot=None, config=config)


def _run(coro):
    return asyncio.run(coro)


def test_get_index_returns_login_page_when_not_logged_in(app_with_config) -> None:
    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                resp = await client.get("/admin/")
                assert resp.status == 200
                text = await resp.text()
        assert "MonolithBot Admin" in text
        assert "Log in" in text
        assert "username" in text and "password" in text

    _run(run())


def test_get_index_redirects_to_dashboard_when_logged_in(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "secret")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                await client.post(
                    "/admin/login", data={"username": "admin", "password": "secret"}
                )
                resp = await client.get("/admin/", allow_redirects=False)
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/dashboard"
                await resp.release()

    _run(run())


def test_post_login_creates_file_on_first_login(
    app_with_config, login_file_path: str
) -> None:
    assert not Path(login_file_path).exists()

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                resp = await client.post(
                    "/admin/login",
                    data={"username": "firstadmin", "password": "firstpass"},
                    allow_redirects=False,
                )
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/dashboard"
                assert auth.SESSION_COOKIE_NAME in resp.cookies
                await resp.release()

    _run(run())
    assert Path(login_file_path).exists()


def test_post_login_invalid_password_shows_error(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "correct")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                resp = await client.post(
                    "/admin/login", data={"username": "admin", "password": "wrong"}
                )
                assert resp.status == 200
                text = await resp.text()
        assert "Invalid" in text or "error" in text.lower()

    _run(run())


def test_post_login_valid_redirects_and_sets_cookie(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "secret")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                resp = await client.post(
                    "/admin/login",
                    data={"username": "admin", "password": "secret"},
                    allow_redirects=False,
                )
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/dashboard"
                assert auth.SESSION_COOKIE_NAME in resp.cookies
                await resp.release()

    _run(run())


def test_get_logout_clears_cookie_and_redirects(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "secret")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                await client.post(
                    "/admin/login", data={"username": "admin", "password": "secret"}
                )
                resp = await client.get("/admin/logout", allow_redirects=False)
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/"
                set_cookie = resp.headers.get("Set-Cookie", "")
                assert "admin_session" in set_cookie and (
                    "0" in set_cookie or "delete" in set_cookie.lower()
                )
                await resp.release()

    _run(run())


def test_get_dashboard_without_session_redirects_to_index(app_with_config) -> None:
    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                resp = await client.get("/admin/dashboard", allow_redirects=False)
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/"
                await resp.release()

    _run(run())


def test_get_dashboard_with_session_returns_200(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "secret")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                await client.post(
                    "/admin/login", data={"username": "admin", "password": "secret"}
                )
                resp = await client.get("/admin/dashboard")
                assert resp.status == 200
                text = await resp.text()
        assert "Admin" in text
        assert "Users" in text or "Registered users" in text

    _run(run())


def test_get_admin_without_trailing_slash_redirects_when_logged_in(
    app_with_config, login_file_path: str
) -> None:
    auth.first_login_setup(login_file_path, "admin", "secret")

    async def run() -> None:
        async with TestServer(app_with_config) as server:
            async with TestClient(server) as client:
                await client.post(
                    "/admin/login", data={"username": "admin", "password": "secret"}
                )
                resp = await client.get("/admin", allow_redirects=False)
                assert resp.status == 302
                assert resp.headers.get("Location") == "/admin/dashboard"
                await resp.release()

    _run(run())

"""
Unit tests for bot/services/organizr.py - Organizr v2 API client.

Tests cover OrganizrClient (login, user_exists, create_user) and OrganizrService
with mocked HTTP responses.
"""

from unittest.mock import MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses

from bot.services.organizr import (
    OrganizrClient,
    OrganizrService,
    OrganizrUser,
    OrganizrError,
    OrganizrConnectionError,
    OrganizrAuthError,
    OrganizrUserExistsError,
)


# =============================================================================
# OrganizrUser Tests
# =============================================================================


class TestOrganizrUser:
    def test_basic_creation(self) -> None:
        user = OrganizrUser(id=1, username="testuser")
        assert user.id == 1
        assert user.username == "testuser"


# =============================================================================
# OrganizrClient Tests
# =============================================================================


class TestOrganizrClientInit:
    def test_basic_init(self) -> None:
        client = OrganizrClient(
            base_url="http://organizr.local",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://organizr.local"
        assert client.admin_user == "admin"
        assert client.admin_password == "secret"

    def test_url_trailing_slash_removed(self) -> None:
        client = OrganizrClient(
            base_url="http://organizr.local/",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://organizr.local"


class TestOrganizrClientLogin:
    @pytest.fixture
    def client(self) -> OrganizrClient:
        return OrganizrClient(
            base_url="http://organizr.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_login_success(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                payload={"result": "success", "data": None},
            )
            await client._login()
            assert client._logged_in is True
        await client.close()

    @pytest.mark.asyncio
    async def test_login_401(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post("http://organizr.local/api/v2/login", status=401)
            with pytest.raises(OrganizrAuthError):
                await client._login()
        await client.close()

    @pytest.mark.asyncio
    async def test_login_connection_error(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )
            with pytest.raises(OrganizrConnectionError):
                await client._login()
        await client.close()


class TestOrganizrClientUserExists:
    @pytest.fixture
    def client(self) -> OrganizrClient:
        return OrganizrClient(
            base_url="http://organizr.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_user_exists_found(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                payload={"result": "success"},
            )
            mocked.get(
                "http://organizr.local/api/v2/users",
                payload={"result": "success", "data": [{"id": 1, "username": "john"}]},
            )
            result = await client.user_exists("john")
            assert result is True
        await client.close()

    @pytest.mark.asyncio
    async def test_user_exists_not_found(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                payload={"result": "success"},
            )
            mocked.get(
                "http://organizr.local/api/v2/users",
                payload={"result": "success", "data": [{"id": 1, "username": "other"}]},
            )
            result = await client.user_exists("john")
            assert result is False
        await client.close()


class TestOrganizrClientCreateUser:
    @pytest.fixture
    def client(self) -> OrganizrClient:
        return OrganizrClient(
            base_url="http://organizr.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_create_user_success(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                payload={"result": "success"},
            )
            mocked.get(
                "http://organizr.local/api/v2/users",
                payload={"result": "success", "data": []},
            )
            mocked.post(
                "http://organizr.local/api/v2/users",
                payload={
                    "result": "success",
                    "data": {"id": 42, "username": "newuser"},
                },
            )
            user = await client.create_user(
                "newuser", "password123", "newuser@example.com"
            )
            assert user.username == "newuser"
            assert user.id == 42
        await client.close()

    @pytest.mark.asyncio
    async def test_create_user_already_exists(self, client: OrganizrClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://organizr.local/api/v2/login",
                payload={"result": "success"},
            )
            mocked.get(
                "http://organizr.local/api/v2/users",
                payload={
                    "result": "success",
                    "data": [{"id": 1, "username": "existing"}],
                },
            )
            with pytest.raises(OrganizrUserExistsError):
                await client.create_user(
                    "existing", "password123", "existing@example.com"
                )
        await client.close()


# =============================================================================
# OrganizrService Tests
# =============================================================================


class TestOrganizrServiceInit:
    def test_single_url(self) -> None:
        service = OrganizrService(
            urls=["http://organizr.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 1
        assert service.active_url is None

    def test_url_trailing_slashes_stripped(self) -> None:
        service = OrganizrService(
            urls=["http://organizr.local/"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.urls[0] == "http://organizr.local"


class TestOrganizrExceptions:
    def test_error_hierarchy(self) -> None:
        assert issubclass(OrganizrConnectionError, OrganizrError)
        assert issubclass(OrganizrAuthError, OrganizrError)
        assert issubclass(OrganizrUserExistsError, OrganizrError)

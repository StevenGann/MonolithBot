"""
Unit tests for bot/services/romm.py - Romm REST API client.

Tests cover:
    - RommUser dataclass
    - RommClient initialization and basic operations
    - RommService multi-URL failover
    - Error handling and exception classes
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from bot.services.romm import (
    RommClient,
    RommService,
    RommUser,
    RommError,
    RommConnectionError,
    RommAuthError,
    RommUserExistsError,
)


# =============================================================================
# RommUser Tests
# =============================================================================


class TestRommUser:
    """Tests for RommUser dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic RommUser."""
        user = RommUser(
            id=123,
            username="testuser",
            enabled=True,
            role="viewer",
        )
        assert user.id == 123
        assert user.username == "testuser"
        assert user.enabled is True
        assert user.role == "viewer"

    def test_admin_user(self) -> None:
        """Test creating an admin user."""
        user = RommUser(
            id=1,
            username="admin",
            role="admin",
        )
        assert user.role == "admin"

    def test_default_values(self) -> None:
        """Test default values."""
        user = RommUser(
            id=456,
            username="defaultuser",
        )
        assert user.enabled is True  # Default
        assert user.role == "viewer"  # Default

    def test_disabled_user(self) -> None:
        """Test disabled user."""
        user = RommUser(
            id=789,
            username="disabled",
            enabled=False,
        )
        assert user.enabled is False


# =============================================================================
# RommClient Tests
# =============================================================================


class TestRommClientInit:
    """Tests for RommClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = RommClient(
            base_url="http://romm.local",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://romm.local"
        assert client.admin_user == "admin"
        assert client.admin_password == "secret"

    def test_url_trailing_slash_removed(self) -> None:
        """Test trailing slash is removed from URL."""
        client = RommClient(
            base_url="http://romm.local/",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://romm.local"


class TestRommClientCheckHealth:
    """Tests for RommClient.check_health method."""

    @pytest.fixture
    def client(self) -> RommClient:
        """Create a RommClient for testing."""
        return RommClient(
            base_url="http://romm.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_check_health_success(self, client: RommClient) -> None:
        """Test successful health check."""
        with aioresponses() as mocked:
            # Auth endpoint (OAuth2 token)
            mocked.post(
                "http://romm.local/api/token",
                payload={"access_token": "test-token", "token_type": "bearer"},
                headers={"Content-Type": "application/json"},
            )

            result = await client.check_health()
            assert result is True

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_connection_error(self, client: RommClient) -> None:
        """Test health check with connection error."""
        with aioresponses() as mocked:
            mocked.post(
                "http://romm.local/api/token",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(RommConnectionError):
                await client.check_health()

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_auth_failure(self, client: RommClient) -> None:
        """Test health check with authentication failure."""
        with aioresponses() as mocked:
            mocked.post(
                "http://romm.local/api/token",
                status=401,
                payload={"detail": "Invalid credentials"},
                headers={"Content-Type": "application/json"},
            )

            with pytest.raises(RommAuthError):
                await client.check_health()

        await client.close()


class TestRommClientContextManager:
    """Tests for RommClient context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using client as async context manager."""
        async with RommClient(
            base_url="http://romm.local",
            admin_user="admin",
            admin_password="secret",
        ) as client:
            assert client is not None
            assert client.base_url == "http://romm.local"


# =============================================================================
# RommService Tests
# =============================================================================


class TestRommServiceInit:
    """Tests for RommService initialization."""

    def test_single_url(self) -> None:
        """Test service with single URL."""
        service = RommService(
            urls=["http://romm.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 1
        assert service.urls[0] == "http://romm.local"

    def test_multiple_urls(self) -> None:
        """Test service with multiple URLs for failover."""
        service = RommService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 2

    def test_url_trailing_slashes_stripped(self) -> None:
        """Test that trailing slashes are stripped from URLs."""
        service = RommService(
            urls=["http://romm.local/"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.urls[0] == "http://romm.local"

    def test_active_url_initially_none(self) -> None:
        """Test that active_url is None before any operations."""
        service = RommService(
            urls=["http://romm.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.active_url is None


class TestRommServiceFailover:
    """Tests for RommService URL failover."""

    @pytest.mark.asyncio
    async def test_all_urls_fail(self) -> None:
        """Test error when all URLs fail."""
        service = RommService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            mocked.post(
                "http://primary.local/api/token",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )
            mocked.post(
                "http://backup.local/api/token",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(RommConnectionError):
                await service.check_health()

        await service.close()


class TestRommServiceContextManager:
    """Tests for RommService context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using service as async context manager."""
        async with RommService(
            urls=["http://romm.local"],
            admin_user="admin",
            admin_password="secret",
        ) as service:
            assert service is not None
            assert service.urls == ["http://romm.local"]


# =============================================================================
# Exception Tests
# =============================================================================


class TestRommExceptions:
    """Tests for Romm exception classes."""

    def test_romm_error(self) -> None:
        """Test base RommError."""
        error = RommError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_connection_error(self) -> None:
        """Test RommConnectionError."""
        error = RommConnectionError("Cannot connect")
        assert isinstance(error, RommError)
        assert "Cannot connect" in str(error)

    def test_auth_error(self) -> None:
        """Test RommAuthError."""
        error = RommAuthError("Invalid credentials")
        assert isinstance(error, RommError)

    def test_user_exists_error(self) -> None:
        """Test RommUserExistsError."""
        error = RommUserExistsError("User already exists")
        assert isinstance(error, RommError)
        assert "already exists" in str(error)

    def test_exception_hierarchy(self) -> None:
        """Test that all exceptions inherit from RommError."""
        assert issubclass(RommConnectionError, RommError)
        assert issubclass(RommAuthError, RommError)
        assert issubclass(RommUserExistsError, RommError)

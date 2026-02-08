"""
Unit tests for bot/services/navidrome.py - Navidrome REST API client.

Tests cover:
    - NavidromeUser dataclass
    - NavidromeClient initialization and basic operations
    - NavidromeService multi-URL failover
    - Error handling and exception classes
"""

from unittest.mock import MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses

from bot.services.navidrome import (
    NavidromeClient,
    NavidromeService,
    NavidromeUser,
    NavidromeError,
    NavidromeConnectionError,
    NavidromeAuthError,
    NavidromeUserExistsError,
)


# =============================================================================
# NavidromeUser Tests
# =============================================================================


class TestNavidromeUser:
    """Tests for NavidromeUser dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic NavidromeUser."""
        user = NavidromeUser(
            id="uuid-1234",
            user_name="testuser",
            email="test@example.com",
            is_admin=False,
        )
        assert user.id == "uuid-1234"
        assert user.user_name == "testuser"
        assert user.email == "test@example.com"
        assert user.is_admin is False

    def test_admin_user(self) -> None:
        """Test creating an admin user."""
        user = NavidromeUser(
            id="uuid-admin",
            user_name="admin",
            is_admin=True,
        )
        assert user.is_admin is True

    def test_optional_email(self) -> None:
        """Test user without email."""
        user = NavidromeUser(
            id="uuid-minimal",
            user_name="noemail",
        )
        assert user.email is None
        assert user.is_admin is False  # Default


# =============================================================================
# NavidromeClient Tests
# =============================================================================


class TestNavidromeClientInit:
    """Tests for NavidromeClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = NavidromeClient(
            base_url="http://navidrome.local",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://navidrome.local"
        assert client.admin_user == "admin"
        assert client.admin_password == "secret"

    def test_url_trailing_slash_removed(self) -> None:
        """Test trailing slash is removed from URL."""
        client = NavidromeClient(
            base_url="http://navidrome.local/",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://navidrome.local"


class TestNavidromeClientCheckHealth:
    """Tests for NavidromeClient.check_health method."""

    @pytest.fixture
    def client(self) -> NavidromeClient:
        """Create a NavidromeClient for testing."""
        return NavidromeClient(
            base_url="http://navidrome.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_check_health_success(self, client: NavidromeClient) -> None:
        """Test successful health check."""
        with aioresponses() as mocked:
            # Auth endpoint
            mocked.post(
                "http://navidrome.local/auth/login",
                payload={"token": "jwt-token", "id": "admin-uuid"},
                headers={"Content-Type": "application/json"},
            )

            result = await client.check_health()
            assert result is True

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_connection_error(self, client: NavidromeClient) -> None:
        """Test health check with connection error."""
        with aioresponses() as mocked:
            mocked.post(
                "http://navidrome.local/auth/login",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(NavidromeConnectionError):
                await client.check_health()

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_auth_failure(self, client: NavidromeClient) -> None:
        """Test health check with authentication failure."""
        with aioresponses() as mocked:
            mocked.post(
                "http://navidrome.local/auth/login",
                status=401,
                payload={"error": "Invalid credentials"},
                headers={"Content-Type": "application/json"},
            )

            with pytest.raises(NavidromeAuthError):
                await client.check_health()

        await client.close()


class TestNavidromeClientContextManager:
    """Tests for NavidromeClient context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using client as async context manager."""
        async with NavidromeClient(
            base_url="http://navidrome.local",
            admin_user="admin",
            admin_password="secret",
        ) as client:
            assert client is not None
            assert client.base_url == "http://navidrome.local"


# =============================================================================
# NavidromeService Tests
# =============================================================================


class TestNavidromeServiceInit:
    """Tests for NavidromeService initialization."""

    def test_single_url(self) -> None:
        """Test service with single URL."""
        service = NavidromeService(
            urls=["http://navidrome.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 1
        assert service.urls[0] == "http://navidrome.local"

    def test_multiple_urls(self) -> None:
        """Test service with multiple URLs for failover."""
        service = NavidromeService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 2

    def test_url_trailing_slashes_stripped(self) -> None:
        """Test that trailing slashes are stripped from URLs."""
        service = NavidromeService(
            urls=["http://navidrome.local/"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.urls[0] == "http://navidrome.local"

    def test_active_url_initially_none(self) -> None:
        """Test that active_url is None before any operations."""
        service = NavidromeService(
            urls=["http://navidrome.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.active_url is None


class TestNavidromeServiceFailover:
    """Tests for NavidromeService URL failover."""

    @pytest.mark.asyncio
    async def test_all_urls_fail(self) -> None:
        """Test error when all URLs fail."""
        service = NavidromeService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            mocked.post(
                "http://primary.local/auth/login",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )
            mocked.post(
                "http://backup.local/auth/login",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(NavidromeConnectionError):
                await service.check_health()

        await service.close()


class TestNavidromeServiceContextManager:
    """Tests for NavidromeService context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using service as async context manager."""
        async with NavidromeService(
            urls=["http://navidrome.local"],
            admin_user="admin",
            admin_password="secret",
        ) as service:
            assert service is not None
            assert service.urls == ["http://navidrome.local"]


# =============================================================================
# Exception Tests
# =============================================================================


class TestNavidromeExceptions:
    """Tests for Navidrome exception classes."""

    def test_navidrome_error(self) -> None:
        """Test base NavidromeError."""
        error = NavidromeError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_connection_error(self) -> None:
        """Test NavidromeConnectionError."""
        error = NavidromeConnectionError("Cannot connect")
        assert isinstance(error, NavidromeError)
        assert "Cannot connect" in str(error)

    def test_auth_error(self) -> None:
        """Test NavidromeAuthError."""
        error = NavidromeAuthError("Invalid credentials")
        assert isinstance(error, NavidromeError)

    def test_user_exists_error(self) -> None:
        """Test NavidromeUserExistsError."""
        error = NavidromeUserExistsError("User already exists")
        assert isinstance(error, NavidromeError)
        assert "already exists" in str(error)

    def test_exception_hierarchy(self) -> None:
        """Test that all exceptions inherit from NavidromeError."""
        assert issubclass(NavidromeConnectionError, NavidromeError)
        assert issubclass(NavidromeAuthError, NavidromeError)
        assert issubclass(NavidromeUserExistsError, NavidromeError)

"""
Unit tests for bot/services/nextcloud.py - NextCloud OCS API client.

Tests cover:
    - NextCloudUser dataclass
    - NextCloudClient HTTP requests and authentication
    - NextCloudService multi-URL failover
    - User creation, existence checking
    - Error handling for various HTTP responses
"""

from unittest.mock import MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses

from bot.services.nextcloud import (
    NextCloudClient,
    NextCloudService,
    NextCloudUser,
    NextCloudError,
    NextCloudConnectionError,
    NextCloudAuthError,
    NextCloudUserExistsError,
)


# =============================================================================
# NextCloudUser Tests
# =============================================================================


class TestNextCloudUser:
    """Tests for NextCloudUser dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic NextCloudUser."""
        user = NextCloudUser(
            user_id="testuser",
            email="test@example.com",
            display_name="Test User",
        )
        assert user.user_id == "testuser"
        assert user.email == "test@example.com"
        assert user.display_name == "Test User"

    def test_optional_fields(self) -> None:
        """Test user with only required fields."""
        user = NextCloudUser(user_id="minimaluser")
        assert user.user_id == "minimaluser"
        assert user.email is None
        assert user.display_name is None


# =============================================================================
# NextCloudClient Tests
# =============================================================================


class TestNextCloudClientInit:
    """Tests for NextCloudClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = NextCloudClient(
            base_url="http://nextcloud.local",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://nextcloud.local"
        assert client.admin_user == "admin"
        assert client.admin_password == "secret"

    def test_url_trailing_slash_removed(self) -> None:
        """Test trailing slash is removed from URL."""
        client = NextCloudClient(
            base_url="http://nextcloud.local/",
            admin_user="admin",
            admin_password="secret",
        )
        assert client.base_url == "http://nextcloud.local"


class TestNextCloudClientCheckHealth:
    """Tests for NextCloudClient.check_health method."""

    @pytest.fixture
    def client(self) -> NextCloudClient:
        """Create a NextCloudClient for testing."""
        return NextCloudClient(
            base_url="http://nextcloud.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_check_health_success(self, client: NextCloudClient) -> None:
        """Test successful health check."""
        with aioresponses() as mocked:
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/capabilities",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {
                            "version": {"string": "28.0.0"},
                            "capabilities": {},
                        },
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            result = await client.check_health()
            assert result is True

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_connection_error(self, client: NextCloudClient) -> None:
        """Test health check with connection error."""
        with aioresponses() as mocked:
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/capabilities",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(NextCloudConnectionError):
                await client.check_health()

        await client.close()


class TestNextCloudClientUserExists:
    """Tests for NextCloudClient.user_exists method."""

    @pytest.fixture
    def client(self) -> NextCloudClient:
        """Create a NextCloudClient for testing."""
        return NextCloudClient(
            base_url="http://nextcloud.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_user_exists_true(self, client: NextCloudClient) -> None:
        """Test user exists returns true."""
        with aioresponses() as mocked:
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/users/testuser",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"id": "testuser", "displayname": "Test User"},
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            result = await client.user_exists("testuser")
            assert result is True

        await client.close()

    @pytest.mark.asyncio
    async def test_user_exists_false(self, client: NextCloudClient) -> None:
        """Test user exists returns false for non-existent user."""
        with aioresponses() as mocked:
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/users/nonexistent",
                payload={
                    "ocs": {
                        "meta": {"status": "failure", "statuscode": 404},
                        "data": [],
                    }
                },
                status=200,
                headers={"Content-Type": "application/json"},
            )

            result = await client.user_exists("nonexistent")
            assert result is False

        await client.close()

    @pytest.mark.asyncio
    async def test_user_exists_auth_error(self, client: NextCloudClient) -> None:
        """Test user exists with authentication error."""
        with aioresponses() as mocked:
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/users/testuser",
                status=401,
                headers={"Content-Type": "application/json"},
            )

            with pytest.raises(NextCloudAuthError):
                await client.user_exists("testuser")

        await client.close()


class TestNextCloudClientCreateUser:
    """Tests for NextCloudClient.create_user method."""

    @pytest.fixture
    def client(self) -> NextCloudClient:
        """Create a NextCloudClient for testing."""
        return NextCloudClient(
            base_url="http://nextcloud.local",
            admin_user="admin",
            admin_password="secret",
        )

    @pytest.mark.asyncio
    async def test_create_user_success(self, client: NextCloudClient) -> None:
        """Test successful user creation."""
        with aioresponses() as mocked:
            mocked.post(
                "http://nextcloud.local/ocs/v1.php/cloud/users",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"id": "newuser"},
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            user = await client.create_user(
                user_id="newuser",
                password="SecurePass123!",
                email="newuser@example.com",
            )

            assert user.user_id == "newuser"
            assert user.email == "newuser@example.com"

        await client.close()

    @pytest.mark.asyncio
    async def test_create_user_already_exists(self, client: NextCloudClient) -> None:
        """Test creating user that already exists."""
        with aioresponses() as mocked:
            mocked.post(
                "http://nextcloud.local/ocs/v1.php/cloud/users",
                payload={
                    "ocs": {
                        "meta": {
                            "status": "failure",
                            "statuscode": 102,
                            "message": "User already exists",
                        },
                        "data": [],
                    }
                },
                status=200,  # NextCloud returns 200 even for errors
                headers={"Content-Type": "application/json"},
            )

            with pytest.raises(NextCloudUserExistsError):
                await client.create_user(
                    user_id="existinguser",
                    password="SecurePass123!",
                )

        await client.close()


class TestNextCloudClientContextManager:
    """Tests for NextCloudClient context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using client as async context manager."""
        async with NextCloudClient(
            base_url="http://nextcloud.local",
            admin_user="admin",
            admin_password="secret",
        ) as client:
            assert client is not None
            assert client.base_url == "http://nextcloud.local"


# =============================================================================
# NextCloudService Tests
# =============================================================================


class TestNextCloudServiceInit:
    """Tests for NextCloudService initialization."""

    def test_single_url(self) -> None:
        """Test service with single URL."""
        service = NextCloudService(
            urls=["http://nextcloud.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 1
        assert service.urls[0] == "http://nextcloud.local"

    def test_multiple_urls(self) -> None:
        """Test service with multiple URLs for failover."""
        service = NextCloudService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )
        assert len(service.urls) == 2

    def test_url_trailing_slashes_stripped(self) -> None:
        """Test that trailing slashes are stripped from URLs."""
        service = NextCloudService(
            urls=["http://nextcloud.local/"],
            admin_user="admin",
            admin_password="secret",
        )
        assert service.urls[0] == "http://nextcloud.local"


class TestNextCloudServiceFailover:
    """Tests for NextCloudService URL failover."""

    @pytest.mark.asyncio
    async def test_failover_to_backup(self) -> None:
        """Test failover to backup URL when primary fails."""
        service = NextCloudService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            # Primary fails
            mocked.get(
                "http://primary.local/ocs/v1.php/cloud/capabilities",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )
            # Backup succeeds
            mocked.get(
                "http://backup.local/ocs/v1.php/cloud/capabilities",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"version": {"string": "28.0.0"}},
                    }
                },
                headers={"Content-Type": "application/json"},
            )
            # Second call to check_health on the active client
            mocked.get(
                "http://backup.local/ocs/v1.php/cloud/capabilities",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"version": {"string": "28.0.0"}},
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            result = await service.check_health()
            assert result is True
            assert service.active_url == "http://backup.local"

        await service.close()

    @pytest.mark.asyncio
    async def test_all_urls_fail(self) -> None:
        """Test error when all URLs fail."""
        service = NextCloudService(
            urls=["http://primary.local", "http://backup.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            mocked.get(
                "http://primary.local/ocs/v1.php/cloud/capabilities",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )
            mocked.get(
                "http://backup.local/ocs/v1.php/cloud/capabilities",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(NextCloudConnectionError):
                await service.check_health()

        await service.close()


class TestNextCloudServiceUserOperations:
    """Tests for NextCloudService user operations."""

    @pytest.mark.asyncio
    async def test_user_exists(self) -> None:
        """Test checking if user exists through service."""
        service = NextCloudService(
            urls=["http://nextcloud.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            # First call to resolve_url (health check)
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/capabilities",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"version": {"string": "28.0.0"}},
                    }
                },
                headers={"Content-Type": "application/json"},
            )
            # User exists check
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/users/testuser",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"id": "testuser"},
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            result = await service.user_exists("testuser")
            assert result is True

        await service.close()

    @pytest.mark.asyncio
    async def test_create_user(self) -> None:
        """Test creating user through service."""
        service = NextCloudService(
            urls=["http://nextcloud.local"],
            admin_user="admin",
            admin_password="secret",
        )

        with aioresponses() as mocked:
            # First call to resolve_url (health check)
            mocked.get(
                "http://nextcloud.local/ocs/v1.php/cloud/capabilities",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"version": {"string": "28.0.0"}},
                    }
                },
                headers={"Content-Type": "application/json"},
            )
            # Create user
            mocked.post(
                "http://nextcloud.local/ocs/v1.php/cloud/users",
                payload={
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100},
                        "data": {"id": "newuser"},
                    }
                },
                headers={"Content-Type": "application/json"},
            )

            user = await service.create_user(
                user_id="newuser",
                password="SecurePass123!",
                email="new@example.com",
            )

            assert user.user_id == "newuser"

        await service.close()


class TestNextCloudServiceContextManager:
    """Tests for NextCloudService context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using service as async context manager."""
        async with NextCloudService(
            urls=["http://nextcloud.local"],
            admin_user="admin",
            admin_password="secret",
        ) as service:
            assert service is not None
            assert service.urls == ["http://nextcloud.local"]


# =============================================================================
# Exception Tests
# =============================================================================


class TestNextCloudExceptions:
    """Tests for NextCloud exception classes."""

    def test_nextcloud_error(self) -> None:
        """Test base NextCloudError."""
        error = NextCloudError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_connection_error(self) -> None:
        """Test NextCloudConnectionError."""
        error = NextCloudConnectionError("Cannot connect")
        assert isinstance(error, NextCloudError)
        assert "Cannot connect" in str(error)

    def test_auth_error(self) -> None:
        """Test NextCloudAuthError."""
        error = NextCloudAuthError("Invalid credentials")
        assert isinstance(error, NextCloudError)

    def test_user_exists_error(self) -> None:
        """Test NextCloudUserExistsError."""
        error = NextCloudUserExistsError("User already exists")
        assert isinstance(error, NextCloudError)
        assert "already exists" in str(error)

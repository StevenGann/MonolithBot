"""
Unit tests for bot/services/user_registry.py - User registry persistence.

Tests cover:
    - RegisteredUser dataclass creation and serialization
    - UserRegistry initialization and file handling
    - Load and save operations
    - User lookup by Discord ID and username
    - User registration and removal
    - Concurrent access patterns
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from bot.services.user_registry import RegisteredUser, UserRegistry


# =============================================================================
# RegisteredUser Tests
# =============================================================================


class TestRegisteredUser:
    """Tests for RegisteredUser dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic RegisteredUser."""
        user = RegisteredUser(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            registered_at="2024-01-15T10:30:00Z",
            services=["Jellyfin", "NextCloud"],
        )
        assert user.discord_id == 123456789
        assert user.discord_name == "TestUser#1234"
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.services == ["Jellyfin", "NextCloud"]

    def test_default_services_empty_list(self) -> None:
        """Test that services defaults to empty list."""
        user = RegisteredUser(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            registered_at="2024-01-15T10:30:00Z",
        )
        assert user.services == []

    def test_from_dict(self) -> None:
        """Test creating RegisteredUser from dictionary."""
        data = {
            "discord_id": 123456789,
            "discord_name": "TestUser#1234",
            "username": "testuser",
            "email": "test@example.com",
            "registered_at": "2024-01-15T10:30:00Z",
            "services": ["Jellyfin"],
        }
        user = RegisteredUser.from_dict(data)
        assert user.discord_id == 123456789
        assert user.username == "testuser"
        assert user.services == ["Jellyfin"]

    def test_from_dict_missing_services(self) -> None:
        """Test from_dict handles missing services field."""
        data = {
            "discord_id": 123456789,
            "discord_name": "TestUser#1234",
            "username": "testuser",
            "email": "test@example.com",
            "registered_at": "2024-01-15T10:30:00Z",
        }
        user = RegisteredUser.from_dict(data)
        assert user.services == []

    def test_to_dict(self) -> None:
        """Test converting RegisteredUser to dictionary."""
        user = RegisteredUser(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            registered_at="2024-01-15T10:30:00Z",
            services=["Jellyfin"],
        )
        data = user.to_dict()
        assert data["discord_id"] == 123456789
        assert data["discord_name"] == "TestUser#1234"
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert data["services"] == ["Jellyfin"]

    def test_roundtrip(self) -> None:
        """Test that to_dict and from_dict are inverses."""
        original = RegisteredUser(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            registered_at="2024-01-15T10:30:00Z",
            services=["Jellyfin", "NextCloud"],
        )
        data = original.to_dict()
        restored = RegisteredUser.from_dict(data)
        assert restored == original


# =============================================================================
# UserRegistry Initialization Tests
# =============================================================================


class TestUserRegistryInit:
    """Tests for UserRegistry initialization."""

    def test_init_with_string_path(self) -> None:
        """Test initialization with string path."""
        registry = UserRegistry("data/test_users.json")
        assert registry.path == Path("data/test_users.json")

    def test_init_with_path_object(self) -> None:
        """Test initialization with Path object."""
        registry = UserRegistry(Path("data/test_users.json"))
        assert registry.path == Path("data/test_users.json")

    def test_init_user_count_is_zero(self) -> None:
        """Test that user_count starts at zero."""
        registry = UserRegistry("data/test_users.json")
        assert registry.user_count == 0


# =============================================================================
# UserRegistry Load Tests
# =============================================================================


class TestUserRegistryLoad:
    """Tests for UserRegistry.load method."""

    @pytest.mark.asyncio
    async def test_load_creates_empty_registry_if_file_missing(
        self, tmp_path: Path
    ) -> None:
        """Test that load works with non-existent file."""
        registry = UserRegistry(tmp_path / "missing.json")
        await registry.load()
        assert registry.user_count == 0

    @pytest.mark.asyncio
    async def test_load_reads_existing_file(self, tmp_path: Path) -> None:
        """Test loading from an existing file."""
        # Create a test registry file
        registry_path = tmp_path / "users.json"
        data = {
            "users": {
                "123456789": {
                    "discord_id": 123456789,
                    "discord_name": "TestUser#1234",
                    "username": "testuser",
                    "email": "test@example.com",
                    "registered_at": "2024-01-15T10:30:00Z",
                    "services": ["Jellyfin"],
                }
            },
            "usernames": {"testuser": "123456789"},
        }
        with open(registry_path, "w") as f:
            json.dump(data, f)

        registry = UserRegistry(registry_path)
        await registry.load()

        assert registry.user_count == 1
        user = registry.get_by_discord_id(123456789)
        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_load_is_idempotent(self, tmp_path: Path) -> None:
        """Test that calling load multiple times is safe."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()
        await registry.load()  # Should not raise
        await registry.load()  # Should not raise
        assert registry.user_count == 0

    @pytest.mark.asyncio
    async def test_load_invalid_json_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid JSON raises an error."""
        registry_path = tmp_path / "invalid.json"
        with open(registry_path, "w") as f:
            f.write("not valid json {{{")

        registry = UserRegistry(registry_path)
        with pytest.raises(json.JSONDecodeError):
            await registry.load()


# =============================================================================
# UserRegistry Save Tests
# =============================================================================


class TestUserRegistrySave:
    """Tests for UserRegistry.save method."""

    @pytest.mark.asyncio
    async def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Test that save creates parent directories."""
        registry = UserRegistry(tmp_path / "subdir" / "nested" / "users.json")
        await registry.load()
        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )
        await registry.save()

        assert (tmp_path / "subdir" / "nested" / "users.json").exists()

    @pytest.mark.asyncio
    async def test_save_writes_valid_json(self, tmp_path: Path) -> None:
        """Test that save writes valid JSON."""
        registry_path = tmp_path / "users.json"
        registry = UserRegistry(registry_path)
        await registry.load()
        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )
        await registry.save()

        # Read and parse the file
        with open(registry_path) as f:
            data = json.load(f)

        assert "users" in data
        assert "123456789" in data["users"]
        assert data["users"]["123456789"]["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_save_and_reload(self, tmp_path: Path) -> None:
        """Test that saved data can be reloaded."""
        registry_path = tmp_path / "users.json"

        # Save data
        registry1 = UserRegistry(registry_path)
        await registry1.load()
        registry1.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin", "NextCloud"],
        )
        await registry1.save()

        # Reload in a new instance
        registry2 = UserRegistry(registry_path)
        await registry2.load()

        assert registry2.user_count == 1
        user = registry2.get_by_discord_id(123456789)
        assert user is not None
        assert user.username == "testuser"
        assert user.services == ["Jellyfin", "NextCloud"]


# =============================================================================
# UserRegistry Lookup Tests
# =============================================================================


class TestUserRegistryLookup:
    """Tests for UserRegistry lookup methods."""

    @pytest.fixture
    async def registry_with_user(self, tmp_path: Path) -> UserRegistry:
        """Create a registry with one user."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()
        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )
        return registry

    @pytest.mark.asyncio
    async def test_get_by_discord_id_found(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test looking up user by Discord ID."""
        user = registry_with_user.get_by_discord_id(123456789)
        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_get_by_discord_id_not_found(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test looking up non-existent Discord ID."""
        user = registry_with_user.get_by_discord_id(999999999)
        assert user is None

    @pytest.mark.asyncio
    async def test_get_by_username_found(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test looking up user by username."""
        user = registry_with_user.get_by_username("testuser")
        assert user is not None
        assert user.discord_id == 123456789

    @pytest.mark.asyncio
    async def test_get_by_username_case_insensitive(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test that username lookup is case-insensitive."""
        user = registry_with_user.get_by_username("TESTUSER")
        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_get_by_username_not_found(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test looking up non-existent username."""
        user = registry_with_user.get_by_username("nonexistent")
        assert user is None

    @pytest.mark.asyncio
    async def test_is_discord_user_registered_true(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test is_discord_user_registered returns True for registered user."""
        assert registry_with_user.is_discord_user_registered(123456789) is True

    @pytest.mark.asyncio
    async def test_is_discord_user_registered_false(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test is_discord_user_registered returns False for unregistered user."""
        assert registry_with_user.is_discord_user_registered(999999999) is False

    @pytest.mark.asyncio
    async def test_is_username_taken_true(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test is_username_taken returns True for taken username."""
        assert registry_with_user.is_username_taken("testuser") is True

    @pytest.mark.asyncio
    async def test_is_username_taken_case_insensitive(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test is_username_taken is case-insensitive."""
        assert registry_with_user.is_username_taken("TESTUSER") is True

    @pytest.mark.asyncio
    async def test_is_username_taken_false(
        self, registry_with_user: UserRegistry
    ) -> None:
        """Test is_username_taken returns False for available username."""
        assert registry_with_user.is_username_taken("available") is False


# =============================================================================
# UserRegistry Add/Remove Tests
# =============================================================================


class TestUserRegistryAddRemove:
    """Tests for adding and removing users."""

    @pytest.mark.asyncio
    async def test_add_user(self, tmp_path: Path) -> None:
        """Test adding a user."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        user = registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        assert user.discord_id == 123456789
        assert user.username == "testuser"
        assert registry.user_count == 1

    @pytest.mark.asyncio
    async def test_add_user_duplicate_discord_id_raises(self, tmp_path: Path) -> None:
        """Test that adding duplicate Discord ID raises error."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        with pytest.raises(ValueError) as exc_info:
            registry.add_user(
                discord_id=123456789,
                discord_name="AnotherUser#5678",
                username="anotheruser",
                email="another@example.com",
                services=["Jellyfin"],
            )
        assert "already registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_user_duplicate_username_raises(self, tmp_path: Path) -> None:
        """Test that adding duplicate username raises error."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        with pytest.raises(ValueError) as exc_info:
            registry.add_user(
                discord_id=987654321,
                discord_name="AnotherUser#5678",
                username="testuser",  # Same username
                email="another@example.com",
                services=["Jellyfin"],
            )
        assert "already taken" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_user_sets_timestamp(self, tmp_path: Path) -> None:
        """Test that add_user sets a timestamp."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        user = registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        assert user.registered_at is not None
        assert "T" in user.registered_at  # ISO format

    @pytest.mark.asyncio
    async def test_remove_user(self, tmp_path: Path) -> None:
        """Test removing a user."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        removed = registry.remove_user(123456789)

        assert removed is not None
        assert removed.username == "testuser"
        assert registry.user_count == 0
        assert registry.get_by_discord_id(123456789) is None
        assert registry.get_by_username("testuser") is None

    @pytest.mark.asyncio
    async def test_remove_user_not_found(self, tmp_path: Path) -> None:
        """Test removing a non-existent user returns None."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        removed = registry.remove_user(999999999)
        assert removed is None

    @pytest.mark.asyncio
    async def test_update_services(self, tmp_path: Path) -> None:
        """Test updating services for a user."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        registry.add_user(
            discord_id=123456789,
            discord_name="TestUser#1234",
            username="testuser",
            email="test@example.com",
            services=["Jellyfin"],
        )

        updated = registry.update_services(123456789, ["Jellyfin", "NextCloud", "Navidrome"])

        assert updated is not None
        assert updated.services == ["Jellyfin", "NextCloud", "Navidrome"]

    @pytest.mark.asyncio
    async def test_update_services_not_found(self, tmp_path: Path) -> None:
        """Test updating services for non-existent user returns None."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        updated = registry.update_services(999999999, ["Jellyfin"])
        assert updated is None


# =============================================================================
# UserRegistry Get All Users Tests
# =============================================================================


class TestUserRegistryGetAllUsers:
    """Tests for get_all_users method."""

    @pytest.mark.asyncio
    async def test_get_all_users_empty(self, tmp_path: Path) -> None:
        """Test get_all_users on empty registry."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        users = registry.get_all_users()
        assert users == []

    @pytest.mark.asyncio
    async def test_get_all_users_multiple(self, tmp_path: Path) -> None:
        """Test get_all_users with multiple users."""
        registry = UserRegistry(tmp_path / "users.json")
        await registry.load()

        registry.add_user(
            discord_id=111111111,
            discord_name="User1#1111",
            username="user1",
            email="user1@example.com",
            services=["Jellyfin"],
        )
        registry.add_user(
            discord_id=222222222,
            discord_name="User2#2222",
            username="user2",
            email="user2@example.com",
            services=["NextCloud"],
        )
        registry.add_user(
            discord_id=333333333,
            discord_name="User3#3333",
            username="user3",
            email="user3@example.com",
            services=["Romm"],
        )

        users = registry.get_all_users()

        assert len(users) == 3
        usernames = {u.username for u in users}
        assert usernames == {"user1", "user2", "user3"}

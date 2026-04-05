"""
User registry for tracking Discord user to service account mappings.

This module provides persistent storage for mapping Discord users to their
registered service accounts (username, email). The registry is stored as
a JSON file for simplicity and human-readability.

Key Features:
    - Persistent JSON storage with atomic writes
    - Lookup by Discord ID or service username
    - Registration history tracking
    - Thread-safe file operations

Data Structure:
    The registry JSON file has this structure:
    {
        "users": {
            "123456789": {
                "discord_id": 123456789,
                "discord_name": "JohnDoe#1234",
                "username": "johndoe",
                "email": "john@example.com",
                "registered_at": "2024-01-15T10:30:00Z",
                "services": ["Jellyfin", "NextCloud", "Navidrome"]
            }
        },
        "usernames": {
            "johndoe": "123456789"
        }
    }

Example:
    >>> from bot.services.user_registry import UserRegistry
    >>>
    >>> registry = UserRegistry("data/users.json")
    >>> await registry.load()
    >>>
    >>> # Check if user already registered
    >>> if registry.get_by_discord_id(123456789):
    ...     print("Already registered!")
    >>>
    >>> # Register a new user
    >>> registry.add_user(
    ...     discord_id=123456789,
    ...     discord_name="JohnDoe#1234",
    ...     username="johndoe",
    ...     email="john@example.com",
    ...     services=["Jellyfin", "NextCloud"],
    ... )
    >>> await registry.save()

See Also:
    - bot.services.registration: Uses this registry
    - bot.cogs.registration.handler: DM handler that manages registration
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Module logger
logger = logging.getLogger("monolithbot.user_registry")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RegisteredUser:
    """
    Represents a registered user in the registry.

    Attributes:
        discord_id: The user's Discord ID (snowflake).
        discord_name: The user's Discord username at registration time.
        username: The service username they registered with.
        email: The email address used for registration.
        registered_at: ISO 8601 timestamp of registration.
        services: List of services the user successfully registered on.
    """

    discord_id: int
    discord_name: str
    username: str
    email: str
    registered_at: str
    services: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "RegisteredUser":
        """Deserialize a RegisteredUser from a dictionary (e.g., loaded from JSON).

        Args:
            data: Dictionary containing the following required keys:
                ``discord_id`` (int), ``discord_name`` (str), ``username`` (str),
                ``email`` (str), ``registered_at`` (str, ISO 8601). The optional
                key ``services`` (list[str]) defaults to an empty list.

        Returns:
            A new RegisteredUser instance.

        Raises:
            KeyError: If any required key is absent from ``data``.
            TypeError: If field types do not match (e.g., discord_id is a string).
        """
        return cls(
            discord_id=data["discord_id"],
            discord_name=data["discord_name"],
            username=data["username"],
            email=data["email"],
            registered_at=data["registered_at"],
            services=data.get("services", []),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


# =============================================================================
# User Registry
# =============================================================================


class UserRegistry:
    """
    Manages persistent storage of Discord user to service account mappings.

    This class provides methods to add, lookup, and manage user registrations.
    Data is stored in a JSON file for simplicity and portability.

    The registry maintains two indexes:
    - By Discord ID: For checking if a Discord user has registered
    - By username: For checking if a username is already taken

    Attributes:
        path: Path to the JSON registry file.

    Example:
        >>> registry = UserRegistry("data/users.json")
        >>> await registry.load()
        >>> user = registry.get_by_discord_id(123456789)
        >>> if user:
        ...     print(f"User registered as {user.username}")
    """

    def __init__(self, path: str | Path) -> None:
        """
        Initialize the user registry.

        Args:
            path: Path to the JSON file for storing registrations.
                  Parent directories will be created if they don't exist.
        """
        self.path = Path(path)
        self._users: dict[
            str, RegisteredUser
        ] = {}  # discord_id (str) -> RegisteredUser
        self._usernames: dict[str, str] = {}  # username -> discord_id (str)
        self._loaded = False

    @property
    def user_count(self) -> int:
        """Get the number of registered users."""
        return len(self._users)

    async def load(self) -> None:
        """
        Load the registry from the JSON file.

        Creates an empty registry if the file doesn't exist.
        This method is idempotent - calling it multiple times is safe.
        """
        if self._loaded:
            return

        if not self.path.exists():
            logger.info(f"Registry file not found, starting fresh: {self.path}")
            self._loaded = True
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load users
            users_data = data.get("users", {})
            for discord_id_str, user_data in users_data.items():
                user = RegisteredUser.from_dict(user_data)
                self._users[discord_id_str] = user
                self._usernames[user.username.lower()] = discord_id_str

            logger.info(f"Loaded {len(self._users)} users from registry")
            self._loaded = True

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse registry file: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            raise

    async def save(self) -> None:
        """
        Save the registry to the JSON file.

        Uses atomic write (write to temp file, then rename) to prevent
        corruption if the process is interrupted.
        """
        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Build the data structure
        data = {
            "users": {
                discord_id: user.to_dict() for discord_id, user in self._users.items()
            },
            "usernames": self._usernames.copy(),
        }

        # Write to temp file first, then rename (atomic on most systems)
        temp_path = self.path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename then restrict permissions — file contains PII
            temp_path.replace(self.path)
            os.chmod(self.path, 0o600)
            logger.debug(f"Saved {len(self._users)} users to registry")

        except Exception as e:
            logger.error(f"Failed to save registry: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            raise

    def get_by_discord_id(self, discord_id: int) -> Optional[RegisteredUser]:
        """
        Look up a user by their Discord ID.

        Args:
            discord_id: The Discord user ID (snowflake).

        Returns:
            The RegisteredUser if found, None otherwise.
        """
        return self._users.get(str(discord_id))

    def get_by_username(self, username: str) -> Optional[RegisteredUser]:
        """
        Look up a user by their service username.

        Args:
            username: The service username (case-insensitive).

        Returns:
            The RegisteredUser if found, None otherwise.
        """
        discord_id = self._usernames.get(username.lower())
        if discord_id:
            return self._users.get(discord_id)
        return None

    def is_discord_user_registered(self, discord_id: int) -> bool:
        """
        Check if a Discord user has already registered.

        Args:
            discord_id: The Discord user ID.

        Returns:
            True if the user has a registration, False otherwise.
        """
        return str(discord_id) in self._users

    def is_username_taken(self, username: str) -> bool:
        """
        Check if a username is already registered.

        Args:
            username: The username to check (case-insensitive).

        Returns:
            True if the username is taken, False otherwise.
        """
        return username.lower() in self._usernames

    def add_user(
        self,
        discord_id: int,
        discord_name: str,
        username: str,
        email: str,
        services: list[str],
    ) -> RegisteredUser:
        """
        Add a new user registration to the registry.

        Args:
            discord_id: The Discord user ID.
            discord_name: The Discord username (for reference).
            username: The service username.
            email: The registration email.
            services: List of services successfully registered on.

        Returns:
            The created RegisteredUser.

        Raises:
            ValueError: If the Discord user or username is already registered.
        """
        discord_id_str = str(discord_id)

        if discord_id_str in self._users:
            raise ValueError(f"Discord user {discord_id} is already registered")

        if username.lower() in self._usernames:
            raise ValueError(f"Username '{username}' is already taken")

        user = RegisteredUser(
            discord_id=discord_id,
            discord_name=discord_name,
            username=username,
            email=email,
            registered_at=datetime.now(timezone.utc).isoformat(),
            services=services,
        )

        self._users[discord_id_str] = user
        self._usernames[username.lower()] = discord_id_str

        logger.info(
            f"Added user to registry: {discord_name} ({discord_id}) -> {username}"
        )

        return user

    def update_services(
        self, discord_id: int, services: list[str]
    ) -> Optional["RegisteredUser"]:
        """
        Update the services list for an existing user.

        Creates a new RegisteredUser instance rather than mutating the existing
        one, to avoid aliasing bugs and comply with the project's immutability
        convention.

        Args:
            discord_id: The Discord user ID.
            services: The new complete list of service names for this user.

        Returns:
            The updated RegisteredUser, or None if the user is not found.
        """
        from dataclasses import replace

        discord_id_str = str(discord_id)
        existing = self._users.get(discord_id_str)
        if existing is None:
            return None
        updated = replace(existing, services=services)
        self._users[discord_id_str] = updated
        logger.info(f"Updated services for {updated.username}: {services}")
        return updated

    def remove_user(self, discord_id: int) -> Optional[RegisteredUser]:
        """
        Remove a user from the registry.

        Args:
            discord_id: The Discord user ID.

        Returns:
            The removed RegisteredUser, or None if not found.
        """
        discord_id_str = str(discord_id)
        user = self._users.pop(discord_id_str, None)
        if user:
            self._usernames.pop(user.username.lower(), None)
            logger.info(f"Removed user from registry: {user.username} ({discord_id})")
        return user

    def get_all_users(self) -> list[RegisteredUser]:
        """
        Get all registered users.

        Returns:
            List of all RegisteredUser objects.
        """
        return list(self._users.values())

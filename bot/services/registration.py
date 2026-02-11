"""
Registration orchestrator service for MonolithBot.

This module coordinates user registration across multiple services (Jellyfin,
NextCloud, Navidrome, Organizr, Romm). It handles the multi-service registration flow,
password generation, and result aggregation.

Key Features:
    - Single password generation for all services
    - Parallel or sequential service registration
    - Graceful handling of partial failures
    - Detailed per-service result reporting

Example:
    >>> from bot.services.registration import RegistrationService
    >>>
    >>> service = RegistrationService(
    ...     jellyfin_service=jellyfin,
    ...     nextcloud_service=nextcloud,
    ...     navidrome_service=navidrome,
    ...     romm_service=romm,
    ... )
    >>>
    >>> result = await service.register_user("johndoe", "john@example.com")
    >>> print(f"Password: {result.password}")
    >>> for sr in result.services:
    ...     status = "✅" if sr.success else "❌"
    ...     print(f"{status} {sr.service_name}: {sr.message}")

See Also:
    - bot.services.password_utils: Password generation
    - bot.services.jellyfin: Jellyfin user creation
    - bot.services.nextcloud: NextCloud user creation
    - bot.services.navidrome: Navidrome user creation
    - bot.services.organizr: Organizr user creation
    - bot.services.romm: Romm user creation
    - bot.cogs.registration.handler: DM handler that uses this service
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bot.services.password_utils import generate_password

# Module logger
logger = logging.getLogger("monolithbot.registration")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ServiceResult:
    """
    Result of a registration attempt for a single service.

    Attributes:
        service_name: Display name of the service (e.g., "Jellyfin", "NextCloud").
        success: Whether the registration succeeded.
        message: Human-readable status message.
        already_existed: True if the user already had an account on this service.
        error: Optional error message if registration failed.
    """

    service_name: str
    success: bool
    message: str
    already_existed: bool = False
    error: Optional[str] = None


@dataclass
class RegistrationResult:
    """
    Aggregated result of a multi-service registration attempt.

    Attributes:
        username: The username that was registered.
        email: The email address used for registration.
        password: The generated password (same across all services).
        services: List of per-service registration results.
        any_success: True if at least one service registration succeeded.
        all_success: True if all enabled services succeeded.
    """

    username: str
    email: str
    password: str
    services: list[ServiceResult] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        """Check if at least one service registration succeeded."""
        return any(sr.success for sr in self.services)

    @property
    def all_success(self) -> bool:
        """Check if all service registrations succeeded."""
        return all(sr.success for sr in self.services)

    @property
    def new_registrations(self) -> list[ServiceResult]:
        """Get services where a new account was created."""
        return [sr for sr in self.services if sr.success and not sr.already_existed]

    @property
    def already_existed(self) -> list[ServiceResult]:
        """Get services where the user already had an account."""
        return [sr for sr in self.services if sr.already_existed]

    @property
    def failed(self) -> list[ServiceResult]:
        """Get services where registration failed."""
        return [sr for sr in self.services if not sr.success and not sr.already_existed]


@dataclass
class PasswordResetResult:
    """
    Aggregated result of a multi-service password reset attempt.

    Attributes:
        username: The username whose password was reset.
        password: The new password (same across all services).
        services: List of per-service reset results.
        any_success: True if at least one service reset succeeded.
        all_success: True if all enabled services succeeded.
    """

    username: str
    password: str
    services: list[ServiceResult] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        """Check if at least one service password reset succeeded."""
        return any(sr.success for sr in self.services)

    @property
    def all_success(self) -> bool:
        """Check if all service password resets succeeded."""
        return all(sr.success for sr in self.services)

    @property
    def successful(self) -> list[ServiceResult]:
        """Get services where password reset succeeded."""
        return [sr for sr in self.services if sr.success]

    @property
    def failed(self) -> list[ServiceResult]:
        """Get services where password reset failed."""
        return [sr for sr in self.services if not sr.success]


# =============================================================================
# Validation
# =============================================================================


class ValidationError(Exception):
    """Raised when input validation fails."""

    pass


def validate_username(username: str) -> str:
    """
    Validate and normalize a username.

    Usernames must:
    - Be 3-32 characters long
    - Contain only letters, numbers, underscores, and hyphens
    - Start with a letter or number

    Args:
        username: The username to validate.

    Returns:
        The normalized (stripped) username.

    Raises:
        ValidationError: If the username is invalid.
    """
    username = username.strip()

    if not username:
        raise ValidationError("Username cannot be empty")

    if len(username) < 3:
        raise ValidationError("Username must be at least 3 characters")

    if len(username) > 32:
        raise ValidationError("Username must be 32 characters or less")

    # Allow letters, numbers, underscores, hyphens
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", username):
        raise ValidationError(
            "Username must start with a letter or number and contain only "
            "letters, numbers, underscores, and hyphens"
        )

    return username


def validate_email(email: str) -> str:
    """
    Validate and normalize an email address.

    Uses a simple regex that catches most invalid emails without being
    overly strict. The best validation is sending a confirmation email.

    Args:
        email: The email address to validate.

    Returns:
        The normalized (stripped, lowercased) email.

    Raises:
        ValidationError: If the email is invalid.
    """
    email = email.strip().lower()

    if not email:
        raise ValidationError("Email cannot be empty")

    # Simple email validation - must have @ and at least one dot after @
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValidationError("Invalid email address format")

    if len(email) > 254:
        raise ValidationError("Email address is too long")

    return email


# =============================================================================
# Registration Service
# =============================================================================


class RegistrationService:
    """
    Orchestrates user registration across multiple services.

    This service coordinates the registration process, generating a single
    password and attempting to create accounts on all enabled services.

    The service handles:
    - Input validation (username, email format)
    - Password generation
    - Per-service registration attempts
    - Result aggregation and reporting

    Attributes:
        jellyfin_service: Optional Jellyfin service for user creation.
        nextcloud_service: Optional NextCloud service for user creation.
        navidrome_service: Optional Navidrome service for user creation.
        romm_service: Optional Romm service for user creation.

    Example:
        >>> service = RegistrationService(
        ...     jellyfin_service=jellyfin,
        ...     nextcloud_service=nextcloud,
        ... )
        >>> result = await service.register_user("john", "john@example.com")
    """

    def __init__(
        self,
        jellyfin_service=None,
        nextcloud_service=None,
        navidrome_service=None,
        organizr_service=None,
        romm_service=None,
    ) -> None:
        """
        Initialize the registration service.

        Args:
            jellyfin_service: Optional JellyfinService instance.
            nextcloud_service: Optional NextCloudService instance.
            navidrome_service: Optional NavidromeService instance.
            organizr_service: Optional OrganizrService instance.
            romm_service: Optional RommService instance.

        Note:
            Services that are None will be skipped during registration.
            At least one service should be provided.
        """
        self.jellyfin_service = jellyfin_service
        self.nextcloud_service = nextcloud_service
        self.navidrome_service = navidrome_service
        self.organizr_service = organizr_service
        self.romm_service = romm_service

    @property
    def enabled_services(self) -> list[str]:
        """Get list of enabled service names."""
        services = []
        if self.jellyfin_service:
            services.append("Jellyfin")
        if self.nextcloud_service:
            services.append("NextCloud")
        if self.navidrome_service:
            services.append("Navidrome")
        if self.organizr_service:
            services.append("Organizr")
        if self.romm_service:
            services.append("Romm")
        return services

    async def register_user(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
    ) -> RegistrationResult:
        """
        Register a user across all enabled services.

        Validates input, generates a password (if not provided), and attempts
        to create accounts on all enabled services. Each service is attempted
        independently - failures on one service don't prevent attempts on others.

        Args:
            username: The username to register. Will be validated.
            email: The email address. Will be validated.
            password: Optional password. If not provided, a secure password
                will be generated.

        Returns:
            RegistrationResult containing the password and per-service results.

        Raises:
            ValidationError: If username or email validation fails.

        Example:
            >>> result = await service.register_user("johndoe", "john@example.com")
            >>> if result.any_success:
            ...     print(f"Your password is: {result.password}")
        """
        # Validate inputs
        username = validate_username(username)
        email = validate_email(email)

        # Generate password if not provided
        if password is None:
            password = generate_password(length=16)

        logger.info(f"Starting registration for user: {username}")

        # Create result object
        result = RegistrationResult(
            username=username,
            email=email,
            password=password,
        )

        # Attempt registration on each enabled service
        if self.jellyfin_service:
            sr = await self._register_jellyfin(username, password)
            result.services.append(sr)

        if self.nextcloud_service:
            sr = await self._register_nextcloud(username, password, email)
            result.services.append(sr)

        if self.navidrome_service:
            sr = await self._register_navidrome(username, password, email)
            result.services.append(sr)

        if self.organizr_service:
            sr = await self._register_organizr(username, password, email)
            result.services.append(sr)

        if self.romm_service:
            sr = await self._register_romm(username, password, email)
            result.services.append(sr)

        # Log summary
        success_count = len(result.new_registrations)
        existed_count = len(result.already_existed)
        failed_count = len(result.failed)
        logger.info(
            f"Registration complete for {username}: "
            f"{success_count} new, {existed_count} existed, {failed_count} failed"
        )

        return result

    async def _register_jellyfin(
        self, username: str, password: str
    ) -> ServiceResult:
        """Attempt to register user on Jellyfin."""
        try:
            # Check if user already exists
            if await self.jellyfin_service.user_exists(username):
                logger.info(f"Jellyfin: User {username} already exists")
                return ServiceResult(
                    service_name="Jellyfin",
                    success=True,
                    message="Account already exists",
                    already_existed=True,
                )

            # Create the user
            await self.jellyfin_service.create_user(username, password)
            logger.info(f"Jellyfin: Created user {username}")
            return ServiceResult(
                service_name="Jellyfin",
                success=True,
                message="Account created successfully",
            )

        except Exception as e:
            logger.error(f"Jellyfin: Failed to create user {username}: {e}")
            return ServiceResult(
                service_name="Jellyfin",
                success=False,
                message="Registration failed",
                error=str(e),
            )

    async def _register_nextcloud(
        self, username: str, password: str, email: str
    ) -> ServiceResult:
        """Attempt to register user on NextCloud."""
        try:
            # Check if user already exists
            if await self.nextcloud_service.user_exists(username):
                logger.info(f"NextCloud: User {username} already exists")
                return ServiceResult(
                    service_name="NextCloud",
                    success=True,
                    message="Account already exists",
                    already_existed=True,
                )

            # Create the user
            await self.nextcloud_service.create_user(
                user_id=username,
                password=password,
                email=email,
            )
            logger.info(f"NextCloud: Created user {username}")
            return ServiceResult(
                service_name="NextCloud",
                success=True,
                message="Account created successfully",
            )

        except Exception as e:
            logger.error(f"NextCloud: Failed to create user {username}: {e}")
            return ServiceResult(
                service_name="NextCloud",
                success=False,
                message="Registration failed",
                error=str(e),
            )

    async def _register_navidrome(
        self, username: str, password: str, email: str
    ) -> ServiceResult:
        """Attempt to register user on Navidrome."""
        try:
            # Check if user already exists
            if await self.navidrome_service.user_exists(username):
                logger.info(f"Navidrome: User {username} already exists")
                return ServiceResult(
                    service_name="Navidrome",
                    success=True,
                    message="Account already exists",
                    already_existed=True,
                )

            # Create the user
            await self.navidrome_service.create_user(
                user_name=username,
                password=password,
                email=email,
            )
            logger.info(f"Navidrome: Created user {username}")
            return ServiceResult(
                service_name="Navidrome",
                success=True,
                message="Account created successfully",
            )

        except Exception as e:
            logger.error(f"Navidrome: Failed to create user {username}: {e}")
            return ServiceResult(
                service_name="Navidrome",
                success=False,
                message="Registration failed",
                error=str(e),
            )

    async def _register_romm(
        self, username: str, password: str, email: str
    ) -> ServiceResult:
        """Attempt to register user on Romm."""
        try:
            # Check if user already exists
            if await self.romm_service.user_exists(username):
                logger.info(f"Romm: User {username} already exists")
                return ServiceResult(
                    service_name="Romm",
                    success=True,
                    message="Account already exists",
                    already_existed=True,
                )

            # Create the user (Romm API requires email)
            await self.romm_service.create_user(
                username=username,
                password=password,
                email=email,
            )
            logger.info(f"Romm: Created user {username}")
            return ServiceResult(
                service_name="Romm",
                success=True,
                message="Account created successfully",
            )

        except Exception as e:
            logger.error(f"Romm: Failed to create user {username}: {e}")
            return ServiceResult(
                service_name="Romm",
                success=False,
                message="Registration failed",
                error=str(e),
            )

    async def _register_organizr(
        self, username: str, password: str, email: str
    ) -> ServiceResult:
        """Attempt to register user on Organizr."""
        try:
            if await self.organizr_service.user_exists(username):
                logger.info(f"Organizr: User {username} already exists")
                return ServiceResult(
                    service_name="Organizr",
                    success=True,
                    message="Account already exists",
                    already_existed=True,
                )

            await self.organizr_service.create_user(
                username=username,
                password=password,
                email=email,
            )
            logger.info(f"Organizr: Created user {username}")
            return ServiceResult(
                service_name="Organizr",
                success=True,
                message="Account created successfully",
            )

        except Exception as e:
            logger.error(f"Organizr: Failed to create user {username}: {e}")
            return ServiceResult(
                service_name="Organizr",
                success=False,
                message="Registration failed",
                error=str(e),
            )

    # =========================================================================
    # Password Reset
    # =========================================================================

    async def reset_password(
        self,
        username: str,
        password: Optional[str] = None,
    ) -> PasswordResetResult:
        """
        Reset a user's password across all enabled services.

        Generates a new password (if not provided) and attempts to set it
        on all enabled services where the user has an account.

        Args:
            username: The username to reset password for. Will be validated.
            password: Optional password. If not provided, a secure password
                will be generated.

        Returns:
            PasswordResetResult containing the new password and per-service results.

        Raises:
            ValidationError: If username validation fails.

        Example:
            >>> result = await service.reset_password("johndoe")
            >>> if result.any_success:
            ...     print(f"Your new password is: {result.password}")
        """
        # Validate username
        username = validate_username(username)

        # Generate password if not provided
        if password is None:
            password = generate_password(length=16)

        logger.info(f"Starting password reset for user: {username}")

        # Create result object
        result = PasswordResetResult(
            username=username,
            password=password,
        )

        # Attempt password reset on each enabled service
        if self.jellyfin_service:
            sr = await self._reset_jellyfin_password(username, password)
            result.services.append(sr)

        if self.nextcloud_service:
            sr = await self._reset_nextcloud_password(username, password)
            result.services.append(sr)

        if self.navidrome_service:
            sr = await self._reset_navidrome_password(username, password)
            result.services.append(sr)

        if self.romm_service:
            sr = await self._reset_romm_password(username, password)
            result.services.append(sr)

        # Log summary
        success_count = len(result.successful)
        failed_count = len(result.failed)
        logger.info(
            f"Password reset complete for {username}: "
            f"{success_count} succeeded, {failed_count} failed"
        )

        return result

    async def _reset_jellyfin_password(
        self, username: str, password: str
    ) -> ServiceResult:
        """Attempt to reset password on Jellyfin."""
        try:
            # Check if user exists
            if not await self.jellyfin_service.user_exists(username):
                logger.info(f"Jellyfin: User {username} does not exist, skipping")
                return ServiceResult(
                    service_name="Jellyfin",
                    success=False,
                    message="User not found",
                    error="User does not have an account on this service",
                )

            # Reset the password
            await self.jellyfin_service.set_password(username, password)
            logger.info(f"Jellyfin: Reset password for {username}")
            return ServiceResult(
                service_name="Jellyfin",
                success=True,
                message="Password reset successfully",
            )

        except Exception as e:
            logger.error(f"Jellyfin: Failed to reset password for {username}: {e}")
            return ServiceResult(
                service_name="Jellyfin",
                success=False,
                message="Password reset failed",
                error=str(e),
            )

    async def _reset_nextcloud_password(
        self, username: str, password: str
    ) -> ServiceResult:
        """Attempt to reset password on NextCloud."""
        try:
            # Check if user exists
            if not await self.nextcloud_service.user_exists(username):
                logger.info(f"NextCloud: User {username} does not exist, skipping")
                return ServiceResult(
                    service_name="NextCloud",
                    success=False,
                    message="User not found",
                    error="User does not have an account on this service",
                )

            # Reset the password
            await self.nextcloud_service.set_password(username, password)
            logger.info(f"NextCloud: Reset password for {username}")
            return ServiceResult(
                service_name="NextCloud",
                success=True,
                message="Password reset successfully",
            )

        except Exception as e:
            logger.error(f"NextCloud: Failed to reset password for {username}: {e}")
            return ServiceResult(
                service_name="NextCloud",
                success=False,
                message="Password reset failed",
                error=str(e),
            )

    async def _reset_navidrome_password(
        self, username: str, password: str
    ) -> ServiceResult:
        """Attempt to reset password on Navidrome."""
        try:
            # Check if user exists
            if not await self.navidrome_service.user_exists(username):
                logger.info(f"Navidrome: User {username} does not exist, skipping")
                return ServiceResult(
                    service_name="Navidrome",
                    success=False,
                    message="User not found",
                    error="User does not have an account on this service",
                )

            # Reset the password
            await self.navidrome_service.set_password(username, password)
            logger.info(f"Navidrome: Reset password for {username}")
            return ServiceResult(
                service_name="Navidrome",
                success=True,
                message="Password reset successfully",
            )

        except Exception as e:
            logger.error(f"Navidrome: Failed to reset password for {username}: {e}")
            return ServiceResult(
                service_name="Navidrome",
                success=False,
                message="Password reset failed",
                error=str(e),
            )

    async def _reset_romm_password(
        self, username: str, password: str
    ) -> ServiceResult:
        """Attempt to reset password on Romm."""
        try:
            # Check if user exists
            if not await self.romm_service.user_exists(username):
                logger.info(f"Romm: User {username} does not exist, skipping")
                return ServiceResult(
                    service_name="Romm",
                    success=False,
                    message="User not found",
                    error="User does not have an account on this service",
                )

            # Reset the password
            await self.romm_service.set_password(username, password)
            logger.info(f"Romm: Reset password for {username}")
            return ServiceResult(
                service_name="Romm",
                success=True,
                message="Password reset successfully",
            )

        except Exception as e:
            logger.error(f"Romm: Failed to reset password for {username}: {e}")
            return ServiceResult(
                service_name="Romm",
                success=False,
                message="Password reset failed",
                error=str(e),
            )

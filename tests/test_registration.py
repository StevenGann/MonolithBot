"""
Unit tests for bot/services/registration.py - Registration orchestrator service.

Tests cover:
    - ServiceResult and RegistrationResult dataclasses
    - Username and email validation
    - RegistrationService orchestration logic
    - Error handling and partial failure scenarios
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services.registration import (
    ServiceResult,
    RegistrationResult,
    RegistrationService,
    ValidationError,
    validate_username,
    validate_email,
)


# =============================================================================
# ServiceResult Tests
# =============================================================================


class TestServiceResult:
    """Tests for ServiceResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic ServiceResult."""
        result = ServiceResult(
            service_name="Jellyfin",
            success=True,
            message="Account created successfully",
        )
        assert result.service_name == "Jellyfin"
        assert result.success is True
        assert result.message == "Account created successfully"
        assert result.already_existed is False
        assert result.error is None

    def test_already_existed(self) -> None:
        """Test result for existing user."""
        result = ServiceResult(
            service_name="NextCloud",
            success=True,
            message="Account already exists",
            already_existed=True,
        )
        assert result.already_existed is True
        assert result.success is True

    def test_failure(self) -> None:
        """Test result for failed registration."""
        result = ServiceResult(
            service_name="Navidrome",
            success=False,
            message="Failed to create account",
            error="Connection timeout",
        )
        assert result.success is False
        assert result.error == "Connection timeout"


# =============================================================================
# RegistrationResult Tests
# =============================================================================


class TestRegistrationResult:
    """Tests for RegistrationResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic RegistrationResult."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
        )
        assert result.username == "testuser"
        assert result.email == "test@example.com"
        assert result.password == "SecurePass123!"
        assert result.services == []

    def test_any_success_with_success(self) -> None:
        """Test any_success property when one succeeds."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.any_success is True

    def test_any_success_all_fail(self) -> None:
        """Test any_success property when all fail."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=False, message="Failed"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.any_success is False

    def test_all_success_true(self) -> None:
        """Test all_success property when all succeed."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult("NextCloud", success=True, message="Created"),
            ],
        )
        assert result.all_success is True

    def test_all_success_false(self) -> None:
        """Test all_success property when one fails."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.all_success is False

    def test_new_registrations(self) -> None:
        """Test new_registrations property."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult(
                    "NextCloud", success=True, message="Exists", already_existed=True
                ),
                ServiceResult("Navidrome", success=False, message="Failed"),
            ],
        )
        new_regs = result.new_registrations
        assert len(new_regs) == 1
        assert new_regs[0].service_name == "Jellyfin"

    def test_already_existed_property(self) -> None:
        """Test already_existed property."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult(
                    "NextCloud", success=True, message="Exists", already_existed=True
                ),
            ],
        )
        existed = result.already_existed
        assert len(existed) == 1
        assert existed[0].service_name == "NextCloud"

    def test_failed_property(self) -> None:
        """Test failed property."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="SecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Created"),
                ServiceResult("Navidrome", success=False, message="Failed"),
                ServiceResult("Romm", success=False, message="Error"),
            ],
        )
        failed = result.failed
        assert len(failed) == 2
        assert failed[0].service_name == "Navidrome"
        assert failed[1].service_name == "Romm"


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidateUsername:
    """Tests for validate_username function."""

    def test_valid_username(self) -> None:
        """Test valid username."""
        assert validate_username("johndoe") == "johndoe"

    def test_valid_username_with_numbers(self) -> None:
        """Test valid username with numbers."""
        assert validate_username("john123") == "john123"

    def test_valid_username_with_underscore(self) -> None:
        """Test valid username with underscore."""
        assert validate_username("john_doe") == "john_doe"

    def test_valid_username_with_hyphen(self) -> None:
        """Test valid username with hyphen."""
        assert validate_username("john-doe") == "john-doe"

    def test_username_starts_with_number(self) -> None:
        """Test username starting with number is valid."""
        assert validate_username("123john") == "123john"

    def test_strips_whitespace(self) -> None:
        """Test whitespace is stripped."""
        assert validate_username("  johndoe  ") == "johndoe"

    def test_empty_username(self) -> None:
        """Test empty username raises error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_username("")
        assert "cannot be empty" in str(exc_info.value)

    def test_username_too_short(self) -> None:
        """Test username too short raises error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_username("jo")
        assert "at least 3" in str(exc_info.value)

    def test_username_too_long(self) -> None:
        """Test username too long raises error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_username("a" * 33)
        assert "32 characters" in str(exc_info.value)

    def test_username_with_special_chars(self) -> None:
        """Test username with special characters raises error."""
        with pytest.raises(ValidationError):
            validate_username("john@doe")

    def test_username_with_spaces(self) -> None:
        """Test username with spaces raises error."""
        with pytest.raises(ValidationError):
            validate_username("john doe")

    def test_username_starting_with_underscore(self) -> None:
        """Test username starting with underscore raises error."""
        with pytest.raises(ValidationError):
            validate_username("_johndoe")


class TestValidateEmail:
    """Tests for validate_email function."""

    def test_valid_email(self) -> None:
        """Test valid email."""
        assert validate_email("test@example.com") == "test@example.com"

    def test_email_normalized_to_lowercase(self) -> None:
        """Test email is normalized to lowercase."""
        assert validate_email("Test@Example.COM") == "test@example.com"

    def test_strips_whitespace(self) -> None:
        """Test whitespace is stripped."""
        assert validate_email("  test@example.com  ") == "test@example.com"

    def test_email_with_subdomain(self) -> None:
        """Test email with subdomain."""
        assert validate_email("test@mail.example.com") == "test@mail.example.com"

    def test_email_with_plus(self) -> None:
        """Test email with plus addressing."""
        assert validate_email("test+tag@example.com") == "test+tag@example.com"

    def test_empty_email(self) -> None:
        """Test empty email raises error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_email("")
        assert "cannot be empty" in str(exc_info.value)

    def test_email_without_at(self) -> None:
        """Test email without @ raises error."""
        with pytest.raises(ValidationError) as exc_info:
            validate_email("testexample.com")
        assert "Invalid email" in str(exc_info.value)

    def test_email_without_domain(self) -> None:
        """Test email without domain raises error."""
        with pytest.raises(ValidationError):
            validate_email("test@")

    def test_email_without_tld(self) -> None:
        """Test email without TLD raises error."""
        with pytest.raises(ValidationError):
            validate_email("test@example")

    def test_email_too_long(self) -> None:
        """Test email too long raises error."""
        long_email = "a" * 250 + "@b.com"
        with pytest.raises(ValidationError) as exc_info:
            validate_email(long_email)
        assert "too long" in str(exc_info.value)


# =============================================================================
# RegistrationService Tests
# =============================================================================


class TestRegistrationServiceInit:
    """Tests for RegistrationService initialization."""

    def test_init_with_all_services(self) -> None:
        """Test initialization with all services."""
        jellyfin = MagicMock()
        nextcloud = MagicMock()
        navidrome = MagicMock()
        romm = MagicMock()

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=nextcloud,
            navidrome_service=navidrome,
            romm_service=romm,
        )

        assert service.jellyfin_service == jellyfin
        assert service.nextcloud_service == nextcloud
        assert service.navidrome_service == navidrome
        assert service.romm_service == romm

    def test_init_with_some_services(self) -> None:
        """Test initialization with only some services."""
        jellyfin = MagicMock()

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        assert service.jellyfin_service == jellyfin
        assert service.nextcloud_service is None

    def test_init_with_no_services(self) -> None:
        """Test initialization with no services."""
        service = RegistrationService(
            jellyfin_service=None,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        assert service.jellyfin_service is None


class TestRegistrationServiceEnabledServices:
    """Tests for RegistrationService.enabled_services property."""

    def test_enabled_services_with_one(self) -> None:
        """Test enabled_services returns service when configured."""
        service = RegistrationService(
            jellyfin_service=MagicMock(),
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )
        assert "Jellyfin" in service.enabled_services
        assert len(service.enabled_services) == 1

    def test_enabled_services_with_all(self) -> None:
        """Test enabled_services returns all configured services."""
        service = RegistrationService(
            jellyfin_service=MagicMock(),
            nextcloud_service=MagicMock(),
            navidrome_service=MagicMock(),
            romm_service=MagicMock(),
        )
        assert len(service.enabled_services) == 4
        assert "Jellyfin" in service.enabled_services
        assert "NextCloud" in service.enabled_services
        assert "Navidrome" in service.enabled_services
        assert "Romm" in service.enabled_services

    def test_enabled_services_empty(self) -> None:
        """Test enabled_services is empty when no services configured."""
        service = RegistrationService(
            jellyfin_service=None,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )
        assert service.enabled_services == []


class TestRegistrationServiceRegisterUser:
    """Tests for RegistrationService.register_user method."""

    @pytest.mark.asyncio
    async def test_register_user_success(self) -> None:
        """Test successful registration on all services."""
        # Create mock services
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=False)
        jellyfin.create_user = AsyncMock(return_value={"id": "jf-123"})

        nextcloud = MagicMock()
        nextcloud.user_exists = AsyncMock(return_value=False)
        nextcloud.create_user = AsyncMock(return_value=MagicMock(user_id="nc-123"))

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=nextcloud,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.register_user("testuser", "test@example.com")

        assert result.username == "testuser"
        assert result.email == "test@example.com"
        assert len(result.password) >= 8  # Password was generated
        assert len(result.services) == 2
        assert result.any_success is True

    @pytest.mark.asyncio
    async def test_register_user_with_provided_password(self) -> None:
        """Test registration with a provided password."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=False)
        jellyfin.create_user = AsyncMock(return_value={"id": "jf-123"})

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.register_user(
            "testuser",
            "test@example.com",
            password="MyCustomPassword123!",
        )

        assert result.password == "MyCustomPassword123!"

    @pytest.mark.asyncio
    async def test_register_user_already_exists(self) -> None:
        """Test registration when user already exists."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=True)

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.register_user("existinguser", "test@example.com")

        assert len(result.services) == 1
        assert result.services[0].already_existed is True
        assert result.services[0].success is True

    @pytest.mark.asyncio
    async def test_register_user_no_services(self) -> None:
        """Test registration with no services configured."""
        service = RegistrationService(
            jellyfin_service=None,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.register_user("testuser", "test@example.com")

        assert result.services == []
        assert result.any_success is False

    @pytest.mark.asyncio
    async def test_register_user_validation_error(self) -> None:
        """Test registration with invalid input."""
        service = RegistrationService(
            jellyfin_service=MagicMock(),
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        with pytest.raises(ValidationError):
            await service.register_user("", "test@example.com")

        with pytest.raises(ValidationError):
            await service.register_user("testuser", "invalid-email")


# =============================================================================
# ValidationError Tests
# =============================================================================


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error(self) -> None:
        """Test ValidationError can be raised and caught."""
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError("Test error message")
        assert "Test error message" in str(exc_info.value)


# =============================================================================
# PasswordResetResult Tests
# =============================================================================


class TestPasswordResetResult:
    """Tests for PasswordResetResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic PasswordResetResult."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
        )
        assert result.username == "testuser"
        assert result.password == "NewSecurePass123!"
        assert result.services == []

    def test_any_success_with_success(self) -> None:
        """Test any_success property when one succeeds."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Password updated"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.any_success is True

    def test_any_success_all_fail(self) -> None:
        """Test any_success property when all fail."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=False, message="Failed"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.any_success is False

    def test_all_success_true(self) -> None:
        """Test all_success property when all succeed."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Password updated"),
                ServiceResult("NextCloud", success=True, message="Password updated"),
            ],
        )
        assert result.all_success is True

    def test_all_success_false(self) -> None:
        """Test all_success property when one fails."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Password updated"),
                ServiceResult("NextCloud", success=False, message="Failed"),
            ],
        )
        assert result.all_success is False

    def test_successful_property(self) -> None:
        """Test successful property returns only successful services."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Password updated"),
                ServiceResult("NextCloud", success=False, message="Failed"),
                ServiceResult("Navidrome", success=True, message="Password updated"),
            ],
        )
        successful = result.successful
        assert len(successful) == 2
        assert all(sr.success for sr in successful)

    def test_failed_property(self) -> None:
        """Test failed property returns only failed services."""
        from bot.services.registration import PasswordResetResult

        result = PasswordResetResult(
            username="testuser",
            password="NewSecurePass123!",
            services=[
                ServiceResult("Jellyfin", success=True, message="Password updated"),
                ServiceResult("NextCloud", success=False, message="Failed"),
                ServiceResult("Navidrome", success=False, message="Failed"),
            ],
        )
        failed = result.failed
        assert len(failed) == 2
        assert all(not sr.success for sr in failed)


# =============================================================================
# RegistrationService Password Reset Tests
# =============================================================================


class TestRegistrationServiceResetPassword:
    """Tests for RegistrationService.reset_password method."""

    @pytest.mark.asyncio
    async def test_reset_password_success(self) -> None:
        """Test successful password reset on all services."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=True)
        jellyfin.set_password = AsyncMock(return_value=True)

        nextcloud = MagicMock()
        nextcloud.user_exists = AsyncMock(return_value=True)
        nextcloud.set_password = AsyncMock(return_value=True)

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=nextcloud,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.reset_password("testuser")

        assert result.username == "testuser"
        assert result.password is not None
        assert len(result.password) >= 16
        assert len(result.services) == 2
        assert result.all_success is True

        jellyfin.set_password.assert_called_once()
        nextcloud.set_password.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_password_with_custom_password(self) -> None:
        """Test password reset with custom password."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=True)
        jellyfin.set_password = AsyncMock(return_value=True)

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.reset_password("testuser", "MyCustomPassword123!")

        assert result.password == "MyCustomPassword123!"
        jellyfin.set_password.assert_called_once_with(
            "testuser", "MyCustomPassword123!"
        )

    @pytest.mark.asyncio
    async def test_reset_password_user_not_found(self) -> None:
        """Test password reset when user doesn't exist on service."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=False)

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.reset_password("nonexistent")

        assert len(result.services) == 1
        assert result.services[0].success is False
        assert "not found" in result.services[0].message.lower()

    @pytest.mark.asyncio
    async def test_reset_password_partial_failure(self) -> None:
        """Test password reset with partial failure."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=True)
        jellyfin.set_password = AsyncMock(return_value=True)

        nextcloud = MagicMock()
        nextcloud.user_exists = AsyncMock(return_value=True)
        nextcloud.set_password = AsyncMock(side_effect=Exception("Connection error"))

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=nextcloud,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.reset_password("testuser")

        assert result.any_success is True
        assert result.all_success is False
        assert len(result.successful) == 1
        assert len(result.failed) == 1

    @pytest.mark.asyncio
    async def test_reset_password_no_services(self) -> None:
        """Test password reset with no services configured."""
        service = RegistrationService(
            jellyfin_service=None,
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        result = await service.reset_password("testuser")

        assert result.services == []
        assert result.any_success is False

    @pytest.mark.asyncio
    async def test_reset_password_validation_error(self) -> None:
        """Test password reset with invalid username."""
        service = RegistrationService(
            jellyfin_service=MagicMock(),
            nextcloud_service=None,
            navidrome_service=None,
            romm_service=None,
        )

        with pytest.raises(ValidationError):
            await service.reset_password("")

    @pytest.mark.asyncio
    async def test_reset_password_all_services(self) -> None:
        """Test password reset on all four services."""
        jellyfin = MagicMock()
        jellyfin.user_exists = AsyncMock(return_value=True)
        jellyfin.set_password = AsyncMock(return_value=True)

        nextcloud = MagicMock()
        nextcloud.user_exists = AsyncMock(return_value=True)
        nextcloud.set_password = AsyncMock(return_value=True)

        navidrome = MagicMock()
        navidrome.user_exists = AsyncMock(return_value=True)
        navidrome.set_password = AsyncMock(return_value=True)

        romm = MagicMock()
        romm.user_exists = AsyncMock(return_value=True)
        romm.set_password = AsyncMock(return_value=True)

        service = RegistrationService(
            jellyfin_service=jellyfin,
            nextcloud_service=nextcloud,
            navidrome_service=navidrome,
            romm_service=romm,
        )

        result = await service.reset_password("testuser", "NewPassword123!")

        assert len(result.services) == 4
        assert result.all_success is True
        assert all(
            sr.service_name in ["Jellyfin", "NextCloud", "Navidrome", "Romm"]
            for sr in result.services
        )

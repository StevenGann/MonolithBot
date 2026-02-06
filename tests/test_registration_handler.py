"""
Unit tests for bot/cogs/registration/handler.py - Registration DM handler cog.

Tests cover:
    - RegistrationCog initialization and lifecycle
    - DM message parsing and registration flow
    - Slash command handling
    - Embed creation for various scenarios
    - Error handling and validation
    - Help message display
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.cogs.registration.handler import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    RegistrationCog,
    setup,
)
from bot.services.registration import (
    RegistrationResult,
    ServiceResult,
    ValidationError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_bot() -> MagicMock:
    """Create a mock MonolithBot instance."""
    bot = MagicMock()
    bot.config.registration.enabled = True
    bot.jellyfin_service = MagicMock()
    bot.nextcloud_service = MagicMock()
    bot.navidrome_service = MagicMock()
    bot.romm_service = MagicMock()
    return bot


@pytest.fixture
def cog(mock_bot: MagicMock) -> RegistrationCog:
    """Create a RegistrationCog instance."""
    return RegistrationCog(mock_bot)


@pytest.fixture
def mock_dm_channel() -> MagicMock:
    """Create a mock DM channel."""
    channel = MagicMock(spec=discord.DMChannel)
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=AsyncMock())
    return channel


@pytest.fixture
def mock_dm_message(mock_dm_channel: MagicMock) -> MagicMock:
    """Create a mock DM message."""
    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.channel = mock_dm_channel
    message.content = "register testuser test@example.com"
    return message


@pytest.fixture
def mock_interaction() -> MagicMock:
    """Create a mock Discord interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.DMChannel)
    interaction.user.name = "TestUser"
    interaction.user.id = 123456789
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def successful_result() -> RegistrationResult:
    """Create a successful registration result."""
    return RegistrationResult(
        username="testuser",
        email="test@example.com",
        password="SecurePass123!",
        services=[
            ServiceResult("Jellyfin", success=True, message="Created"),
            ServiceResult("NextCloud", success=True, message="Created"),
        ],
    )


@pytest.fixture
def partial_result() -> RegistrationResult:
    """Create a partial registration result (some success, some failure)."""
    return RegistrationResult(
        username="testuser",
        email="test@example.com",
        password="SecurePass123!",
        services=[
            ServiceResult("Jellyfin", success=True, message="Created"),
            ServiceResult("NextCloud", success=False, message="Failed", error="Connection timeout"),
        ],
    )


@pytest.fixture
def already_exists_result() -> RegistrationResult:
    """Create a result where user already exists on some services."""
    return RegistrationResult(
        username="testuser",
        email="test@example.com",
        password="SecurePass123!",
        services=[
            ServiceResult("Jellyfin", success=True, message="Exists", already_existed=True),
            ServiceResult("NextCloud", success=True, message="Created"),
        ],
    )


@pytest.fixture
def failed_result() -> RegistrationResult:
    """Create a failed registration result."""
    return RegistrationResult(
        username="testuser",
        email="test@example.com",
        password="SecurePass123!",
        services=[
            ServiceResult("Jellyfin", success=False, message="Failed", error="Server error"),
            ServiceResult("NextCloud", success=False, message="Failed", error="Auth failed"),
        ],
    )


# =============================================================================
# Cog Initialization Tests
# =============================================================================


class TestRegistrationCogInit:
    """Tests for RegistrationCog initialization."""

    def test_init_stores_bot_reference(self, cog: RegistrationCog, mock_bot: MagicMock) -> None:
        """Test that __init__ stores the bot reference."""
        assert cog.bot == mock_bot

    def test_init_registration_service_is_none(self, cog: RegistrationCog) -> None:
        """Test that registration_service starts as None."""
        assert cog.registration_service is None


class TestRegistrationCogLoad:
    """Tests for RegistrationCog cog_load."""

    @pytest.mark.asyncio
    async def test_cog_load_creates_registration_service(
        self, cog: RegistrationCog, mock_bot: MagicMock
    ) -> None:
        """Test that cog_load creates the RegistrationService."""
        await cog.cog_load()

        assert cog.registration_service is not None
        assert cog.registration_service.jellyfin_service == mock_bot.jellyfin_service
        assert cog.registration_service.nextcloud_service == mock_bot.nextcloud_service
        assert cog.registration_service.navidrome_service == mock_bot.navidrome_service
        assert cog.registration_service.romm_service == mock_bot.romm_service

    @pytest.mark.asyncio
    async def test_cog_load_handles_missing_services(self, mock_bot: MagicMock) -> None:
        """Test cog_load when some services are not available on bot."""
        # Remove some service attributes
        del mock_bot.nextcloud_service
        del mock_bot.navidrome_service

        cog = RegistrationCog(mock_bot)
        await cog.cog_load()

        assert cog.registration_service is not None
        assert cog.registration_service.jellyfin_service == mock_bot.jellyfin_service
        assert cog.registration_service.nextcloud_service is None
        assert cog.registration_service.navidrome_service is None


class TestRegistrationCogUnload:
    """Tests for RegistrationCog cog_unload."""

    @pytest.mark.asyncio
    async def test_cog_unload_clears_registration_service(self, cog: RegistrationCog) -> None:
        """Test that cog_unload clears the registration service."""
        await cog.cog_load()
        assert cog.registration_service is not None

        await cog.cog_unload()
        assert cog.registration_service is None


# =============================================================================
# DM Message Handling Tests
# =============================================================================


class TestOnMessageIgnoreConditions:
    """Tests for on_message ignore conditions."""

    @pytest.mark.asyncio
    async def test_ignores_bot_messages(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that bot messages are ignored."""
        mock_dm_message.author.bot = True

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_dm_messages(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that non-DM messages are ignored."""
        mock_dm_message.channel = MagicMock(spec=discord.TextChannel)

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_when_registration_disabled(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that messages are ignored when registration is disabled."""
        cog.bot.config.registration.enabled = False

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_not_called()


class TestOnMessageParsing:
    """Tests for on_message parsing."""

    @pytest.mark.asyncio
    async def test_sends_help_for_non_register_message(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that help is sent for messages not starting with 'register'."""
        await cog.cog_load()
        mock_dm_message.content = "hello"

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Registration" in embed.title

    @pytest.mark.asyncio
    async def test_sends_usage_error_for_missing_arguments(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that usage error is sent when arguments are missing."""
        await cog.cog_load()
        mock_dm_message.content = "register testuser"

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Invalid Format" in embed.title

    @pytest.mark.asyncio
    async def test_parses_valid_register_command(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that valid register command is parsed correctly."""
        await cog.cog_load()
        mock_dm_message.content = "register myuser myemail@test.com"

        # Mock the registration service
        cog.registration_service.register_user = AsyncMock(
            return_value=RegistrationResult(
                username="myuser",
                email="myemail@test.com",
                password="TestPass123!",
                services=[ServiceResult("Jellyfin", True, "Created")],
            )
        )

        await cog.on_message(mock_dm_message)

        cog.registration_service.register_user.assert_called_once_with(
            "myuser", "myemail@test.com"
        )

    @pytest.mark.asyncio
    async def test_register_command_case_insensitive(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that 'REGISTER' works (case insensitive)."""
        await cog.cog_load()
        mock_dm_message.content = "REGISTER myuser myemail@test.com"

        cog.registration_service.register_user = AsyncMock(
            return_value=RegistrationResult(
                username="myuser",
                email="myemail@test.com",
                password="TestPass123!",
                services=[ServiceResult("Jellyfin", True, "Created")],
            )
        )

        await cog.on_message(mock_dm_message)

        cog.registration_service.register_user.assert_called_once()


class TestOnMessageValidation:
    """Tests for on_message validation."""

    @pytest.mark.asyncio
    async def test_sends_validation_error_for_invalid_username(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test validation error for invalid username."""
        await cog.cog_load()
        mock_dm_message.content = "register ab test@example.com"  # Too short

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Error" in embed.title

    @pytest.mark.asyncio
    async def test_sends_validation_error_for_invalid_email(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test validation error for invalid email."""
        await cog.cog_load()
        mock_dm_message.content = "register validuser notanemail"

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Error" in embed.title


class TestOnMessageRegistration:
    """Tests for on_message registration flow."""

    @pytest.mark.asyncio
    async def test_successful_registration_sends_result_embed(
        self, cog: RegistrationCog, mock_dm_message: MagicMock, successful_result: RegistrationResult
    ) -> None:
        """Test that successful registration sends result embed."""
        await cog.cog_load()
        cog.registration_service.register_user = AsyncMock(return_value=successful_result)

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Complete" in embed.title

    @pytest.mark.asyncio
    async def test_registration_error_sends_error_embed(
        self, cog: RegistrationCog, mock_dm_message: MagicMock
    ) -> None:
        """Test that registration errors send error embed."""
        await cog.cog_load()
        cog.registration_service.register_user = AsyncMock(
            side_effect=Exception("Database error")
        )

        await cog.on_message(mock_dm_message)

        mock_dm_message.channel.send.assert_called_once()
        call_args = mock_dm_message.channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert "Error" in embed.title


# =============================================================================
# Slash Command Tests
# =============================================================================


class TestRegisterSlashCommand:
    """Tests for /register slash command."""

    @pytest.mark.asyncio
    async def test_disabled_registration_sends_error(
        self, cog: RegistrationCog, mock_interaction: MagicMock
    ) -> None:
        """Test that disabled registration sends error message."""
        cog.bot.config.registration.enabled = False
        mock_interaction.response.send_message = AsyncMock()

        # Call the callback directly
        await cog.register_command.callback(cog, mock_interaction, "testuser", "test@example.com")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "disabled" in call_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_non_dm_redirects_to_dm(
        self, cog: RegistrationCog, mock_interaction: MagicMock
    ) -> None:
        """Test that non-DM usage redirects user to DM."""
        mock_interaction.channel = MagicMock(spec=discord.TextChannel)  # Not a DM

        await cog.register_command.callback(cog, mock_interaction, "testuser", "test@example.com")

        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "DM" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_dm_processes_registration(
        self, cog: RegistrationCog, mock_interaction: MagicMock, successful_result: RegistrationResult
    ) -> None:
        """Test that DM interaction processes registration."""
        await cog.cog_load()
        cog.registration_service.register_user = AsyncMock(return_value=successful_result)

        await cog.register_command.callback(cog, mock_interaction, "testuser", "test@example.com")

        mock_interaction.response.defer.assert_called_once()
        cog.registration_service.register_user.assert_called_once()
        mock_interaction.followup.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_error_in_slash_command(
        self, cog: RegistrationCog, mock_interaction: MagicMock
    ) -> None:
        """Test validation error handling in slash command."""
        await cog.cog_load()

        await cog.register_command.callback(cog, mock_interaction, "ab", "test@example.com")  # Too short

        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        embed = call_args.kwargs.get("embed")
        assert embed is not None
        assert embed.color == COLOR_ERROR


# =============================================================================
# Embed Creation Tests
# =============================================================================


class TestCreateResultEmbed:
    """Tests for _create_result_embed method."""

    def test_successful_result_embed(
        self, cog: RegistrationCog, successful_result: RegistrationResult
    ) -> None:
        """Test embed for successful registration."""
        embed = cog._create_result_embed(successful_result)

        assert "Complete" in embed.title
        assert embed.color == COLOR_SUCCESS
        assert any("Password" in f.name for f in embed.fields)

    def test_partial_result_embed(
        self, cog: RegistrationCog, partial_result: RegistrationResult
    ) -> None:
        """Test embed for partial registration."""
        embed = cog._create_result_embed(partial_result)

        assert "Partial" in embed.title
        assert embed.color == COLOR_WARNING

    def test_failed_result_embed(
        self, cog: RegistrationCog, failed_result: RegistrationResult
    ) -> None:
        """Test embed for failed registration."""
        embed = cog._create_result_embed(failed_result)

        assert "Failed" in embed.title
        assert embed.color == COLOR_ERROR

    def test_already_existed_shows_info_icon(
        self, cog: RegistrationCog, already_exists_result: RegistrationResult
    ) -> None:
        """Test that already existed services show info icon."""
        embed = cog._create_result_embed(already_exists_result)

        services_field = next((f for f in embed.fields if f.name == "Services"), None)
        assert services_field is not None
        assert "ℹ️" in services_field.value
        assert "Already exists" in services_field.value

    def test_embed_has_username_field(
        self, cog: RegistrationCog, successful_result: RegistrationResult
    ) -> None:
        """Test that embed includes username field."""
        embed = cog._create_result_embed(successful_result)

        username_field = next((f for f in embed.fields if f.name == "Username"), None)
        assert username_field is not None
        assert "testuser" in username_field.value

    def test_embed_has_email_field(
        self, cog: RegistrationCog, successful_result: RegistrationResult
    ) -> None:
        """Test that embed includes email field."""
        embed = cog._create_result_embed(successful_result)

        email_field = next((f for f in embed.fields if f.name == "Email"), None)
        assert email_field is not None
        assert "test@example.com" in email_field.value

    def test_embed_has_password_spoiler(
        self, cog: RegistrationCog, successful_result: RegistrationResult
    ) -> None:
        """Test that password is wrapped in spoiler tags."""
        embed = cog._create_result_embed(successful_result)

        password_field = next((f for f in embed.fields if "Password" in f.name), None)
        assert password_field is not None
        assert "||" in password_field.value  # Spoiler tags

    def test_embed_has_footer_warning(
        self, cog: RegistrationCog, successful_result: RegistrationResult
    ) -> None:
        """Test that embed has footer with password warning."""
        embed = cog._create_result_embed(successful_result)

        assert embed.footer is not None
        assert "Save" in embed.footer.text

    def test_failed_result_no_password_field(
        self, cog: RegistrationCog, failed_result: RegistrationResult
    ) -> None:
        """Test that failed result doesn't show password."""
        embed = cog._create_result_embed(failed_result)

        password_field = next((f for f in embed.fields if "Password" in f.name), None)
        assert password_field is None

    def test_error_message_truncated_if_long(self, cog: RegistrationCog) -> None:
        """Test that long error messages are truncated."""
        result = RegistrationResult(
            username="testuser",
            email="test@example.com",
            password="Pass123!",
            services=[
                ServiceResult(
                    "Jellyfin",
                    success=False,
                    message="Failed",
                    error="A" * 100,  # Very long error
                ),
            ],
        )

        embed = cog._create_result_embed(result)

        services_field = next((f for f in embed.fields if f.name == "Services"), None)
        assert services_field is not None
        assert "..." in services_field.value


class TestCreateErrorEmbed:
    """Tests for _create_error_embed method."""

    def test_error_embed_has_title(self, cog: RegistrationCog) -> None:
        """Test that error embed has correct title."""
        embed = cog._create_error_embed("Test error message")

        assert "Error" in embed.title

    def test_error_embed_has_description(self, cog: RegistrationCog) -> None:
        """Test that error embed includes the error message."""
        embed = cog._create_error_embed("Test error message")

        assert embed.description == "Test error message"

    def test_error_embed_color(self, cog: RegistrationCog) -> None:
        """Test that error embed has error color."""
        embed = cog._create_error_embed("Test error")

        assert embed.color == COLOR_ERROR


class TestCreateHelpEmbed:
    """Tests for _create_help_embed method."""

    @pytest.mark.asyncio
    async def test_help_embed_has_title(self, cog: RegistrationCog) -> None:
        """Test that help embed has correct title."""
        await cog.cog_load()
        embed = cog._create_help_embed()

        assert "Registration" in embed.title

    @pytest.mark.asyncio
    async def test_help_embed_has_usage_field(self, cog: RegistrationCog) -> None:
        """Test that help embed has usage field."""
        await cog.cog_load()
        embed = cog._create_help_embed()

        usage_field = next((f for f in embed.fields if f.name == "Usage"), None)
        assert usage_field is not None
        assert "register" in usage_field.value.lower()

    @pytest.mark.asyncio
    async def test_help_embed_has_example_field(self, cog: RegistrationCog) -> None:
        """Test that help embed has example field."""
        await cog.cog_load()
        embed = cog._create_help_embed()

        example_field = next((f for f in embed.fields if f.name == "Example"), None)
        assert example_field is not None

    @pytest.mark.asyncio
    async def test_help_embed_shows_available_services(self, cog: RegistrationCog) -> None:
        """Test that help embed shows available services."""
        await cog.cog_load()
        embed = cog._create_help_embed()

        services_field = next(
            (f for f in embed.fields if "Services" in f.name), None
        )
        assert services_field is not None

    @pytest.mark.asyncio
    async def test_help_embed_color(self, cog: RegistrationCog) -> None:
        """Test that help embed has info color."""
        await cog.cog_load()
        embed = cog._create_help_embed()

        assert embed.color == COLOR_INFO


# =============================================================================
# Response Helper Tests
# =============================================================================


class TestResponseHelpers:
    """Tests for response helper methods."""

    @pytest.mark.asyncio
    async def test_send_help(
        self, cog: RegistrationCog, mock_dm_channel: MagicMock
    ) -> None:
        """Test _send_help sends help embed."""
        await cog.cog_load()
        await cog._send_help(mock_dm_channel)

        mock_dm_channel.send.assert_called_once()
        call_args = mock_dm_channel.send.call_args
        assert "embed" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_send_usage_error(
        self, cog: RegistrationCog, mock_dm_channel: MagicMock
    ) -> None:
        """Test _send_usage_error sends usage error embed."""
        await cog._send_usage_error(mock_dm_channel)

        mock_dm_channel.send.assert_called_once()
        call_args = mock_dm_channel.send.call_args
        embed = call_args.kwargs.get("embed")
        assert "Invalid Format" in embed.title

    @pytest.mark.asyncio
    async def test_send_validation_error(
        self, cog: RegistrationCog, mock_dm_channel: MagicMock
    ) -> None:
        """Test _send_validation_error sends error embed."""
        await cog._send_validation_error(mock_dm_channel, "Username too short")

        mock_dm_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_error(
        self, cog: RegistrationCog, mock_dm_channel: MagicMock
    ) -> None:
        """Test _send_error sends error embed."""
        await cog._send_error(mock_dm_channel, "Something went wrong")

        mock_dm_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_result_embed(
        self, cog: RegistrationCog, mock_dm_channel: MagicMock, successful_result: RegistrationResult
    ) -> None:
        """Test _send_result_embed sends result embed."""
        await cog._send_result_embed(mock_dm_channel, successful_result)

        mock_dm_channel.send.assert_called_once()


# =============================================================================
# Setup Function Tests
# =============================================================================


class TestSetupFunction:
    """Tests for the module setup function."""

    @pytest.mark.asyncio
    async def test_setup_adds_cog(self, mock_bot: MagicMock) -> None:
        """Test that setup adds the cog to the bot."""
        mock_bot.add_cog = AsyncMock()

        await setup(mock_bot)

        mock_bot.add_cog.assert_called_once()
        call_args = mock_bot.add_cog.call_args
        assert isinstance(call_args.args[0], RegistrationCog)


# =============================================================================
# Color Constants Tests
# =============================================================================


class TestColorConstants:
    """Tests for color constants."""

    def test_success_color_is_green(self) -> None:
        """Test that success color is green."""
        assert COLOR_SUCCESS == discord.Color.green()

    def test_error_color_is_red(self) -> None:
        """Test that error color is red."""
        assert COLOR_ERROR == discord.Color.red()

    def test_warning_color_is_orange(self) -> None:
        """Test that warning color is orange."""
        assert COLOR_WARNING == discord.Color.orange()

    def test_info_color_is_blue(self) -> None:
        """Test that info color is blue."""
        assert COLOR_INFO == discord.Color.blue()

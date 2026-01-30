"""
Tests for Minecraft cogs (health monitoring and player announcements).

These tests verify the behavior of MinecraftHealthCog and MinecraftPlayersCog,
including state management, notifications, and player tracking.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.cogs.minecraft.health import MinecraftHealthCog
from bot.cogs.minecraft.players import MinecraftPlayersCog
from bot.services.minecraft import (
    MinecraftConnectionError,
    MinecraftServerState,
    MinecraftServerStatus,
    MinecraftService,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_bot(minecraft_config):
    """Create a mock MonolithBot instance with Minecraft service."""
    bot = MagicMock()
    bot.config.minecraft = minecraft_config
    bot.config.jellyfin.schedule.timezone = "America/Los_Angeles"
    bot.minecraft_service = MagicMock(spec=MinecraftService)

    # Set up server state mocks
    server_state = MinecraftServerState(
        name="Survival",
        urls=["mc.example.com:25565", "backup.example.com:25565"],
        online=None,
    )
    bot.minecraft_service.get_server_state.return_value = server_state
    bot.minecraft_service.get_server_names.return_value = ["Survival"]
    bot.minecraft_service.get_all_servers.return_value = [server_state]

    return bot


@pytest.fixture
def mock_channel():
    """Create a mock Discord channel."""
    channel = MagicMock()
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def sample_status():
    """Create a sample MinecraftServerStatus."""
    return MinecraftServerStatus(
        online=True,
        player_count=3,
        max_players=20,
        player_names={"Steve", "Alex", "Notch"},
        motd="Welcome to the server!",
        version="1.20.4",
        latency_ms=42.5,
    )


# =============================================================================
# MinecraftHealthCog Tests
# =============================================================================


class TestMinecraftHealthCogInit:
    """Test MinecraftHealthCog initialization."""

    def test_cog_creates_scheduler(self, mock_bot):
        """Test that cog creates a scheduler on init."""
        with patch("bot.cogs.minecraft.health.create_scheduler") as mock_create:
            mock_create.return_value = MagicMock()
            cog = MinecraftHealthCog(mock_bot)
            assert cog.scheduler is not None

    def test_cog_stores_bot_reference(self, mock_bot):
        """Test that cog stores bot reference."""
        with patch("bot.cogs.minecraft.health.create_scheduler"):
            cog = MinecraftHealthCog(mock_bot)
            assert cog.bot is mock_bot


class TestMinecraftHealthCogFormatDuration:
    """Test the _format_duration helper method."""

    @pytest.fixture
    def cog(self, mock_bot):
        """Create cog for testing."""
        with patch("bot.cogs.minecraft.health.create_scheduler"):
            return MinecraftHealthCog(mock_bot)

    def test_format_seconds(self, cog):
        """Test formatting of seconds."""
        assert cog._format_duration(1) == "1 second"
        assert cog._format_duration(30) == "30 seconds"

    def test_format_minutes(self, cog):
        """Test formatting of minutes."""
        assert cog._format_duration(60) == "1 minute"
        assert cog._format_duration(90) == "1 minute"
        assert cog._format_duration(120) == "2 minutes"
        assert cog._format_duration(3599) == "59 minutes"

    def test_format_hours(self, cog):
        """Test formatting of hours."""
        assert cog._format_duration(3600) == "1 hour"
        assert cog._format_duration(3660) == "1h 1m"
        assert cog._format_duration(7200) == "2 hours"

    def test_format_days(self, cog):
        """Test formatting of days."""
        assert cog._format_duration(86400) == "1 day"
        assert cog._format_duration(90000) == "1d 1h"
        assert cog._format_duration(172800) == "2 days"


class TestMinecraftHealthCogNotifications:
    """Test notification methods."""

    @pytest.fixture
    def cog(self, mock_bot, mock_channel):
        """Create cog with mocked channel."""
        mock_bot.get_channel.return_value = mock_channel
        with patch("bot.cogs.minecraft.health.create_scheduler"):
            return MinecraftHealthCog(mock_bot)

    @pytest.mark.asyncio
    async def test_send_online_notification(self, cog, mock_channel, sample_status):
        """Test sending online notification."""
        await cog._send_online_notification("Survival", sample_status, None)
        mock_channel.send.assert_called_once()

        # Verify embed was created
        call_kwargs = mock_channel.send.call_args
        assert "embed" in call_kwargs.kwargs
        embed = call_kwargs.kwargs["embed"]
        assert "Online" in embed.title
        assert "Survival" in embed.title

    @pytest.mark.asyncio
    async def test_send_online_notification_with_downtime(
        self, cog, mock_channel, sample_status
    ):
        """Test online notification includes downtime."""
        downtime = timedelta(hours=1, minutes=30)
        await cog._send_online_notification("Survival", sample_status, downtime)

        call_kwargs = mock_channel.send.call_args
        embed = call_kwargs.kwargs["embed"]

        # Check that downtime field exists
        field_names = [field.name for field in embed.fields]
        assert "Downtime" in field_names

    @pytest.mark.asyncio
    async def test_send_offline_notification(self, cog, mock_channel):
        """Test sending offline notification."""
        await cog._send_offline_notification("Survival", "Connection refused")
        mock_channel.send.assert_called_once()

        call_kwargs = mock_channel.send.call_args
        embed = call_kwargs.kwargs["embed"]
        assert "Offline" in embed.title
        assert "Survival" in embed.title

    @pytest.mark.asyncio
    async def test_send_notification_no_channel(self, cog, mock_bot, sample_status):
        """Test notification gracefully handles missing channel."""
        mock_bot.get_channel.return_value = None
        await cog._send_online_notification("Survival", sample_status, None)
        # Should not raise, just log error


class TestMinecraftHealthCogStateHandling:
    """Test server state handling."""

    @pytest.fixture
    def cog(self, mock_bot, mock_channel):
        """Create cog for testing."""
        mock_bot.get_channel.return_value = mock_channel
        with patch("bot.cogs.minecraft.health.create_scheduler"):
            return MinecraftHealthCog(mock_bot)

    @pytest.mark.asyncio
    async def test_handle_server_online_from_unknown(
        self, cog, mock_bot, mock_channel, sample_status
    ):
        """Test handling server coming online from unknown state."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = None  # Unknown state

        await cog._handle_server_online("Survival", sample_status)

        # Should mark online but NOT notify (unknown → online is initial state)
        mock_bot.minecraft_service.mark_online.assert_called_with("Survival")
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_server_online_from_offline(
        self, cog, mock_bot, mock_channel, sample_status
    ):
        """Test handling server recovering from offline."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = False  # Was offline
        state.went_offline = datetime.now(timezone.utc) - timedelta(minutes=5)

        await cog._handle_server_online("Survival", sample_status)

        # Should mark online AND notify
        mock_bot.minecraft_service.mark_online.assert_called_with("Survival")
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_server_offline_from_online(self, cog, mock_bot, mock_channel):
        """Test handling server going offline from online state."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = True  # Was online

        await cog._handle_server_offline("Survival", "Connection refused")

        # Should mark offline AND notify
        mock_bot.minecraft_service.mark_offline.assert_called_with("Survival")
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_server_offline_stays_offline(
        self, cog, mock_bot, mock_channel
    ):
        """Test handling server that was already offline."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = False  # Already offline

        await cog._handle_server_offline("Survival", "Connection refused")

        # Should NOT mark offline again or notify
        mock_bot.minecraft_service.mark_offline.assert_not_called()
        mock_channel.send.assert_not_called()


# =============================================================================
# MinecraftPlayersCog Tests
# =============================================================================


class TestMinecraftPlayersCogInit:
    """Test MinecraftPlayersCog initialization."""

    def test_cog_creates_scheduler(self, mock_bot):
        """Test that cog creates a scheduler on init."""
        with patch("bot.cogs.minecraft.players.create_scheduler") as mock_create:
            mock_create.return_value = MagicMock()
            cog = MinecraftPlayersCog(mock_bot)
            assert cog.scheduler is not None

    def test_cog_not_initialized_at_start(self, mock_bot):
        """Test that cog starts as not initialized."""
        with patch("bot.cogs.minecraft.players.create_scheduler"):
            cog = MinecraftPlayersCog(mock_bot)
            assert cog._initialized is False


class TestMinecraftPlayersCogNotifications:
    """Test player announcement methods."""

    @pytest.fixture
    def cog(self, mock_bot, mock_channel):
        """Create cog with mocked channel."""
        mock_bot.get_channel.return_value = mock_channel
        with patch("bot.cogs.minecraft.players.create_scheduler"):
            cog = MinecraftPlayersCog(mock_bot)
            cog._initialized = True
            return cog

    @pytest.mark.asyncio
    async def test_send_single_player_join(self, cog, mock_channel, sample_status):
        """Test announcement for single player join."""
        new_players = {"Steve"}
        await cog._send_join_announcement("Survival", new_players, sample_status)

        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args
        embed = call_kwargs.kwargs["embed"]
        assert "Steve" in embed.title
        assert "joined" in embed.title
        assert "Survival" in embed.title

    @pytest.mark.asyncio
    async def test_send_multiple_player_join(self, cog, mock_channel, sample_status):
        """Test announcement for multiple players joining."""
        new_players = {"Steve", "Alex"}
        await cog._send_join_announcement("Survival", new_players, sample_status)

        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args
        embed = call_kwargs.kwargs["embed"]
        assert "2 players" in embed.title
        assert "joined" in embed.title

    @pytest.mark.asyncio
    async def test_join_announcement_includes_player_count(
        self, cog, mock_channel, sample_status
    ):
        """Test that join announcement includes online player count."""
        new_players = {"Steve"}
        await cog._send_join_announcement("Survival", new_players, sample_status)

        call_kwargs = mock_channel.send.call_args
        embed = call_kwargs.kwargs["embed"]
        field_names = [field.name for field in embed.fields]
        assert "Online Now" in field_names

    @pytest.mark.asyncio
    async def test_send_announcement_no_channel(self, cog, mock_bot, sample_status):
        """Test announcement gracefully handles missing channel."""
        mock_bot.get_channel.return_value = None
        await cog._send_join_announcement("Survival", {"Steve"}, sample_status)
        # Should not raise


class TestMinecraftPlayersCogPlayerTracking:
    """Test player change detection and processing."""

    @pytest.fixture
    def cog(self, mock_bot, mock_channel):
        """Create cog for testing."""
        mock_bot.get_channel.return_value = mock_channel
        with patch("bot.cogs.minecraft.players.create_scheduler"):
            cog = MinecraftPlayersCog(mock_bot)
            cog._initialized = True
            return cog

    @pytest.mark.asyncio
    async def test_process_player_changes_with_new_players(
        self, cog, mock_bot, mock_channel, sample_status
    ):
        """Test processing when new players are detected."""
        # Service returns new players
        mock_bot.minecraft_service.detect_player_joins.return_value = {"NewPlayer"}

        await cog._process_player_changes("Survival", sample_status)

        # Should send announcement
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_player_changes_no_new_players(
        self, cog, mock_bot, mock_channel, sample_status
    ):
        """Test processing when no new players joined."""
        # Service returns empty set
        mock_bot.minecraft_service.detect_player_joins.return_value = set()

        await cog._process_player_changes("Survival", sample_status)

        # Should NOT send announcement
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_player_changes_hidden_player_list(
        self, cog, mock_bot, mock_channel
    ):
        """Test processing when server hides player list."""
        status = MinecraftServerStatus(
            online=True,
            player_count=5,
            max_players=20,
            players_hidden=True,
        )

        await cog._process_player_changes("Survival", status)

        # Should NOT attempt join detection or send announcement
        mock_bot.minecraft_service.detect_player_joins.assert_not_called()
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_server_players_skips_offline(
        self, cog, mock_bot, mock_channel
    ):
        """Test that player check skips offline servers."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = False

        await cog._check_server_players("Survival")

        # Should not attempt status check
        mock_bot.minecraft_service.get_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_server_players_handles_error(
        self, cog, mock_bot, mock_channel
    ):
        """Test that player check handles errors gracefully."""
        state = mock_bot.minecraft_service.get_server_state.return_value
        state.online = True
        mock_bot.minecraft_service.get_status.side_effect = MinecraftConnectionError(
            "Connection failed"
        )

        # Should not raise
        await cog._check_server_players("Survival")
        mock_channel.send.assert_not_called()


# =============================================================================
# Cog Setup Tests
# =============================================================================


class TestMinecraftCogSetup:
    """Test cog setup functions."""

    @pytest.mark.asyncio
    async def test_health_cog_setup(self, mock_bot):
        """Test health cog setup function."""
        from bot.cogs.minecraft.health import setup

        mock_bot.add_cog = AsyncMock()
        with patch("bot.cogs.minecraft.health.create_scheduler"):
            await setup(mock_bot)
        mock_bot.add_cog.assert_called_once()

    @pytest.mark.asyncio
    async def test_players_cog_setup(self, mock_bot):
        """Test players cog setup function."""
        from bot.cogs.minecraft.players import setup

        mock_bot.add_cog = AsyncMock()
        with patch("bot.cogs.minecraft.players.create_scheduler"):
            await setup(mock_bot)
        mock_bot.add_cog.assert_called_once()

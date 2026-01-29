"""Unit tests for bot/cogs/jellyfin/health.py - Jellyfin health monitoring cog.

Tests cover:
    - Server status state transitions
    - Notification triggering logic
    - Duration formatting
    - Health check handling
"""

import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.jellyfin import (
    JellyfinConnectionError,
    JellyfinError,
    ServerInfo,
)


# =============================================================================
# Helper function to create a mock HealthCog
# =============================================================================


def create_health_cog(mock_bot: MagicMock) -> Any:
    """Create a JellyfinHealthCog with mocked dependencies."""
    with patch("bot.cogs.jellyfin.health.create_scheduler"):
        from bot.cogs.jellyfin.health import JellyfinHealthCog

        cog = JellyfinHealthCog(mock_bot)
        # Create a mock jellyfin client
        cog.jellyfin = MagicMock()
        cog.jellyfin.check_health = AsyncMock()
        return cog


# =============================================================================
# Duration Formatting Tests
# =============================================================================


class TestFormatDuration:
    """Tests for _format_duration method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    def test_format_seconds_singular(self, cog: Any) -> None:
        """Test formatting 1 second."""
        assert cog._format_duration(1) == "1 second"

    def test_format_seconds_plural(self, cog: Any) -> None:
        """Test formatting multiple seconds."""
        assert cog._format_duration(45) == "45 seconds"

    def test_format_minute_singular(self, cog: Any) -> None:
        """Test formatting 1 minute."""
        assert cog._format_duration(60) == "1 minute"

    def test_format_minutes_plural(self, cog: Any) -> None:
        """Test formatting multiple minutes."""
        assert cog._format_duration(120) == "2 minutes"

    def test_format_minutes_boundary(self, cog: Any) -> None:
        """Test formatting 59 minutes."""
        assert cog._format_duration(59 * 60) == "59 minutes"

    def test_format_hour_singular(self, cog: Any) -> None:
        """Test formatting 1 hour."""
        assert cog._format_duration(3600) == "1 hour"

    def test_format_hours_plural(self, cog: Any) -> None:
        """Test formatting multiple hours."""
        assert cog._format_duration(7200) == "2 hours"

    def test_format_hours_with_minutes(self, cog: Any) -> None:
        """Test formatting hours and minutes."""
        assert cog._format_duration(3660) == "1h 1m"  # 1 hour 1 minute

    def test_format_hours_boundary(self, cog: Any) -> None:
        """Test formatting 23 hours."""
        assert cog._format_duration(23 * 3600) == "23 hours"

    def test_format_day_singular(self, cog: Any) -> None:
        """Test formatting 1 day."""
        assert cog._format_duration(86400) == "1 day"

    def test_format_days_plural(self, cog: Any) -> None:
        """Test formatting multiple days."""
        assert cog._format_duration(172800) == "2 days"

    def test_format_days_with_hours(self, cog: Any) -> None:
        """Test formatting days and hours."""
        assert cog._format_duration(90000) == "1d 1h"  # 25 hours


# =============================================================================
# Server Online Handler Tests
# =============================================================================


class TestHandleServerOnline:
    """Tests for _handle_server_online method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_updates_state_to_online(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test that server state is updated to online."""
        cog._server_online = None

        await cog._handle_server_online(server_info)

        assert cog._server_online is True

    @pytest.mark.asyncio
    async def test_updates_last_online_time(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test that last_online timestamp is updated."""
        cog._server_online = None
        cog._last_online = None

        await cog._handle_server_online(server_info)

        assert cog._last_online is not None

    @pytest.mark.asyncio
    async def test_no_notification_when_already_online(
        self, cog: Any, server_info: ServerInfo, mock_bot: MagicMock
    ) -> None:
        """Test no notification when server was already online."""
        cog._server_online = True

        with patch.object(cog, "_send_online_notification") as mock_notify:
            await cog._handle_server_online(server_info)
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_on_recovery(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test notification is sent when server recovers."""
        cog._server_online = False

        with patch.object(
            cog, "_send_online_notification", new_callable=AsyncMock
        ) as mock_notify:
            await cog._handle_server_online(server_info)
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_notification_on_initial_online(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test no notification on initial online state (unknown -> online)."""
        cog._server_online = None

        with patch.object(cog, "_send_online_notification") as mock_notify:
            await cog._handle_server_online(server_info)
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_clears_went_offline_on_recovery(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test _went_offline is cleared on recovery."""
        cog._server_online = False
        cog._went_offline = datetime.now(timezone.utc)

        with patch.object(
            cog, "_send_online_notification", new_callable=AsyncMock
        ):
            await cog._handle_server_online(server_info)

        assert cog._went_offline is None


# =============================================================================
# Server Offline Handler Tests
# =============================================================================


class TestHandleServerOffline:
    """Tests for _handle_server_offline method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_updates_state_to_offline(self, cog: Any) -> None:
        """Test that server state is updated to offline."""
        cog._server_online = True

        with patch.object(
            cog, "_send_offline_notification", new_callable=AsyncMock
        ):
            await cog._handle_server_offline("Connection refused")

        assert cog._server_online is False

    @pytest.mark.asyncio
    async def test_sets_went_offline_time(self, cog: Any) -> None:
        """Test that _went_offline timestamp is set."""
        cog._server_online = True
        cog._went_offline = None

        with patch.object(
            cog, "_send_offline_notification", new_callable=AsyncMock
        ):
            await cog._handle_server_offline("Connection refused")

        assert cog._went_offline is not None

    @pytest.mark.asyncio
    async def test_notification_when_online_to_offline(self, cog: Any) -> None:
        """Test notification when server goes from online to offline."""
        cog._server_online = True

        with patch.object(
            cog, "_send_offline_notification", new_callable=AsyncMock
        ) as mock_notify:
            await cog._handle_server_offline("Connection refused")
            mock_notify.assert_called_once_with("Connection refused")

    @pytest.mark.asyncio
    async def test_notification_when_unknown_to_offline(self, cog: Any) -> None:
        """Test notification when server goes from unknown to offline."""
        cog._server_online = None

        with patch.object(
            cog, "_send_offline_notification", new_callable=AsyncMock
        ) as mock_notify:
            await cog._handle_server_offline("Connection refused")
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_notification_when_already_offline(self, cog: Any) -> None:
        """Test no notification when server is still offline."""
        cog._server_online = False

        with patch.object(cog, "_send_offline_notification") as mock_notify:
            await cog._handle_server_offline("Still offline")
            mock_notify.assert_not_called()


# =============================================================================
# Health Check Runner Tests
# =============================================================================


class TestRunHealthCheck:
    """Tests for _run_health_check method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_calls_handle_online_on_success(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test _handle_server_online is called on successful check."""
        cog.jellyfin.check_health = AsyncMock(return_value=server_info)

        with patch.object(
            cog, "_handle_server_online", new_callable=AsyncMock
        ) as mock_handler:
            await cog._run_health_check()
            mock_handler.assert_called_once_with(server_info)

    @pytest.mark.asyncio
    async def test_calls_handle_offline_on_connection_error(self, cog: Any) -> None:
        """Test _handle_server_offline is called on connection error."""
        cog.jellyfin.check_health = AsyncMock(
            side_effect=JellyfinConnectionError("Connection refused")
        )

        with patch.object(
            cog, "_handle_server_offline", new_callable=AsyncMock
        ) as mock_handler:
            await cog._run_health_check()
            mock_handler.assert_called_once()
            assert "Connection refused" in mock_handler.call_args[0][0]

    @pytest.mark.asyncio
    async def test_calls_handle_offline_on_api_error(self, cog: Any) -> None:
        """Test _handle_server_offline is called on API error."""
        cog.jellyfin.check_health = AsyncMock(
            side_effect=JellyfinError("API error 500")
        )

        with patch.object(
            cog, "_handle_server_offline", new_callable=AsyncMock
        ) as mock_handler:
            await cog._run_health_check()
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_last_server_info(
        self, cog: Any, server_info: ServerInfo
    ) -> None:
        """Test server info is stored on successful check."""
        cog.jellyfin.check_health = AsyncMock(return_value=server_info)
        cog._last_server_info = None

        with patch.object(
            cog, "_handle_server_online", new_callable=AsyncMock
        ):
            await cog._run_health_check()

        assert cog._last_server_info == server_info


# =============================================================================
# Notification Tests
# =============================================================================


class TestSendOnlineNotification:
    """Tests for _send_online_notification method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_returns_early_if_no_channel(
        self, cog: Any, mock_bot: MagicMock, server_info: ServerInfo
    ) -> None:
        """Test returns early if alert channel not found."""
        mock_bot.get_channel.return_value = None

        # Should not raise
        await cog._send_online_notification(server_info, None)

    @pytest.mark.asyncio
    async def test_sends_embed_to_channel(
        self,
        cog: Any,
        mock_bot: MagicMock,
        mock_discord_channel: MagicMock,
        server_info: ServerInfo,
    ) -> None:
        """Test sends embed to the alert channel."""
        mock_bot.get_channel.return_value = mock_discord_channel

        await cog._send_online_notification(server_info, None)

        mock_discord_channel.send.assert_called_once()
        call_kwargs = mock_discord_channel.send.call_args.kwargs
        assert "embed" in call_kwargs
        assert "Online" in call_kwargs["embed"].title

    @pytest.mark.asyncio
    async def test_includes_downtime_in_embed(
        self,
        cog: Any,
        mock_bot: MagicMock,
        mock_discord_channel: MagicMock,
        server_info: ServerInfo,
    ) -> None:
        """Test includes downtime duration in embed."""
        mock_bot.get_channel.return_value = mock_discord_channel
        downtime = timedelta(hours=1, minutes=30)

        await cog._send_online_notification(server_info, downtime)

        embed = mock_discord_channel.send.call_args.kwargs["embed"]
        downtime_field = next(
            (f for f in embed.fields if f.name == "Downtime"), None
        )
        assert downtime_field is not None


class TestSendOfflineNotification:
    """Tests for _send_offline_notification method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_health_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_returns_early_if_no_channel(
        self, cog: Any, mock_bot: MagicMock
    ) -> None:
        """Test returns early if alert channel not found."""
        mock_bot.get_channel.return_value = None

        # Should not raise
        await cog._send_offline_notification("Connection refused")

    @pytest.mark.asyncio
    async def test_sends_embed_to_channel(
        self, cog: Any, mock_bot: MagicMock, mock_discord_channel: MagicMock
    ) -> None:
        """Test sends embed to the alert channel."""
        mock_bot.get_channel.return_value = mock_discord_channel

        await cog._send_offline_notification("Connection refused")

        mock_discord_channel.send.assert_called_once()
        call_kwargs = mock_discord_channel.send.call_args.kwargs
        assert "embed" in call_kwargs
        assert "Offline" in call_kwargs["embed"].title

    @pytest.mark.asyncio
    async def test_includes_error_in_embed(
        self, cog: Any, mock_bot: MagicMock, mock_discord_channel: MagicMock
    ) -> None:
        """Test includes error message in embed."""
        mock_bot.get_channel.return_value = mock_discord_channel

        await cog._send_offline_notification("Connection refused")

        embed = mock_discord_channel.send.call_args.kwargs["embed"]
        error_field = next((f for f in embed.fields if f.name == "Error"), None)
        assert error_field is not None
        assert "Connection refused" in error_field.value

    @pytest.mark.asyncio
    async def test_includes_last_online_time(
        self, cog: Any, mock_bot: MagicMock, mock_discord_channel: MagicMock
    ) -> None:
        """Test includes last online time if available."""
        mock_bot.get_channel.return_value = mock_discord_channel
        cog._last_online = datetime.now(timezone.utc)

        await cog._send_offline_notification("Connection refused")

        embed = mock_discord_channel.send.call_args.kwargs["embed"]
        last_online_field = next(
            (f for f in embed.fields if f.name == "Last Online"), None
        )
        assert last_online_field is not None

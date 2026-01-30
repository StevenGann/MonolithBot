"""Unit tests for bot/cogs/jellyfin/suggestions.py - Jellyfin Suggestions cog.

Tests cover:
    - Embed creation for different suggestion types
    - Random suggestion fetching
    - Scheduled suggestion posting
    - Slash command handling
"""

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.services.jellyfin import JellyfinError, JellyfinItem


# =============================================================================
# Helper function to create a mock SuggestionsCog
# =============================================================================


def create_suggestions_cog(mock_bot: Any) -> Any:
    """Create a JellyfinSuggestionsCog with mocked dependencies."""
    with patch("bot.cogs.jellyfin.suggestions.create_scheduler"):
        from bot.cogs.jellyfin.suggestions import JellyfinSuggestionsCog

        # Set up the mock jellyfin_service on the bot
        mock_bot.jellyfin_service = MagicMock()
        mock_bot.jellyfin_service.get_item_url = MagicMock(
            side_effect=lambda id: f"http://jellyfin/item/{id}"
        )
        mock_bot.jellyfin_service.get_item_image_url = MagicMock(
            side_effect=lambda id: f"http://jellyfin/image/{id}"
        )
        mock_bot.jellyfin_service.get_random_items_by_type = AsyncMock(return_value={})
        mock_bot.jellyfin_service.get_random_item = AsyncMock(return_value=None)

        cog = JellyfinSuggestionsCog(mock_bot)
        return cog


# =============================================================================
# Suggestion Embed Creation Tests
# =============================================================================


class TestCreateSuggestionEmbed:
    """Tests for _create_suggestion_embed method."""

    @pytest.fixture
    def cog(self, mock_bot) -> Any:
        """Create a test cog."""
        return create_suggestions_cog(mock_bot)

    @pytest.fixture
    def movie_item(self) -> JellyfinItem:
        """Create a sample movie item."""
        return JellyfinItem(
            id="movie123",
            name="The Matrix",
            item_type="Movie",
            overview="A computer hacker learns about the true nature of reality.",
            year=1999,
            date_created=datetime.now(timezone.utc),
        )

    def test_movie_embed_creation(self, cog: Any, movie_item: JellyfinItem) -> None:
        """Test embed creation for a movie suggestion."""
        embed = cog._create_suggestion_embed("Movie", movie_item)

        assert embed.title == "🎬 Movie Suggestion"
        assert embed.color == discord.Color.blue()
        assert embed.url == "http://jellyfin/item/movie123"
        assert embed.thumbnail.url == "http://jellyfin/image/movie123"
        # Check that title field exists
        title_field = next((f for f in embed.fields if f.name == "Title"), None)
        assert title_field is not None
        assert title_field.value == "The Matrix (1999)"

    @pytest.fixture
    def series_item(self) -> JellyfinItem:
        """Create a sample series item."""
        return JellyfinItem(
            id="series123",
            name="Breaking Bad",
            item_type="Series",
            overview="A high school chemistry teacher turned methamphetamine manufacturer.",
            year=2008,
            date_created=datetime.now(timezone.utc),
        )

    def test_series_embed_creation(self, cog: Any, series_item: JellyfinItem) -> None:
        """Test embed creation for a series suggestion."""
        embed = cog._create_suggestion_embed("Series", series_item)

        assert embed.title == "📺 TV Show Suggestion"
        assert embed.color == discord.Color.green()
        # Check that title field exists
        title_field = next((f for f in embed.fields if f.name == "Title"), None)
        assert title_field is not None
        assert title_field.value == "Breaking Bad (2008)"

    @pytest.fixture
    def album_item(self) -> JellyfinItem:
        """Create a sample album item."""
        return JellyfinItem(
            id="album123",
            name="Dark Side of the Moon",
            item_type="MusicAlbum",
            overview="Classic progressive rock album.",
            artists=["Pink Floyd"],
            date_created=datetime.now(timezone.utc),
        )

    def test_album_embed_creation(self, cog: Any, album_item: JellyfinItem) -> None:
        """Test embed creation for an album suggestion."""
        embed = cog._create_suggestion_embed("MusicAlbum", album_item)

        assert embed.title == "💿 Album Suggestion"
        assert embed.color == discord.Color.purple()

    def test_long_description_truncated(self, cog: Any, movie_item: JellyfinItem) -> None:
        """Test that long descriptions are truncated."""
        # Create item with very long overview
        long_overview = "A" * 500
        movie_item.overview = long_overview

        embed = cog._create_suggestion_embed("Movie", movie_item)

        # Overview field should be truncated to MAX_DESCRIPTION_LENGTH
        overview_field = next((f for f in embed.fields if f.name == "Overview"), None)
        assert overview_field is not None
        assert len(overview_field.value) <= 303  # 300 + "..."


# =============================================================================
# Post Random Suggestions Tests
# =============================================================================


class TestPostRandomSuggestions:
    """Tests for post_random_suggestions method."""

    @pytest.fixture
    def cog(self, mock_bot) -> Any:
        """Create a test cog."""
        return create_suggestions_cog(mock_bot)

    @pytest.fixture
    def mock_channel(self) -> MagicMock:
        """Create a mock Discord channel."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        return channel

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_channel(
        self, cog: Any, mock_bot: MagicMock
    ) -> None:
        """Test returns 0 when channel is not found."""
        mock_bot.get_channel.return_value = None

        count = await cog.post_random_suggestions()

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_jellyfin(
        self, cog: Any, mock_channel: MagicMock
    ) -> None:
        """Test returns 0 when jellyfin service is not initialized."""
        cog.bot.jellyfin_service = None

        count = await cog.post_random_suggestions(channel=mock_channel)

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_items(
        self, cog: Any, mock_channel: MagicMock
    ) -> None:
        """Test returns 0 when no suggestions found."""
        cog.bot.jellyfin_service.get_random_items_by_type = AsyncMock(return_value={})

        count = await cog.post_random_suggestions(channel=mock_channel)

        assert count == 0
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_count_when_items_found(
        self,
        cog: Any,
        mock_channel: MagicMock,
    ) -> None:
        """Test returns correct count when suggestions are found."""
        # Create test items
        movie_item = JellyfinItem(
            id="movie123",
            name="The Matrix",
            item_type="Movie",
            year=1999,
            date_created=datetime.now(timezone.utc),
        )
        series_item = JellyfinItem(
            id="series123",
            name="Breaking Bad",
            item_type="Series",
            year=2008,
            date_created=datetime.now(timezone.utc),
        )
        suggestions = {
            "Movie": movie_item,
            "Series": series_item,
        }
        cog.bot.jellyfin_service.get_random_items_by_type = AsyncMock(
            return_value=suggestions
        )

        count = await cog.post_random_suggestions(channel=mock_channel)

        assert count == 2
        # Should send header + 2 suggestion embeds
        assert mock_channel.send.call_count == 3

    @pytest.mark.asyncio
    async def test_handles_jellyfin_error(
        self, cog: Any, mock_channel: MagicMock
    ) -> None:
        """Test handles Jellyfin errors gracefully."""
        cog.bot.jellyfin_service.get_random_items_by_type = AsyncMock(
            side_effect=JellyfinError("Connection failed")
        )

        count = await cog.post_random_suggestions(channel=mock_channel)

        assert count == 0
        mock_channel.send.assert_not_called()


# =============================================================================
# Suggest Command Tests
# =============================================================================


class TestSuggestCommand:
    """Tests for suggest_command slash command."""

    @pytest.fixture
    def cog(self, mock_bot) -> Any:
        """Create a test cog."""
        return create_suggestions_cog(mock_bot)

    @pytest.fixture
    def mock_interaction(self) -> MagicMock:
        """Create a mock Discord interaction."""
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        interaction.channel = MagicMock()
        return interaction

    @pytest.mark.asyncio
    async def test_command_with_no_type_posts_all(
        self, cog: Any, mock_interaction: MagicMock
    ) -> None:
        """Test command with no type posts all suggestions."""
        cog.post_random_suggestions = AsyncMock(return_value=3)

        await cog.suggest_command(mock_interaction, content_type=None)

        mock_interaction.response.defer.assert_called_once()
        cog.post_random_suggestions.assert_called_once_with(mock_interaction.channel)

    @pytest.mark.asyncio
    async def test_command_with_type_posts_single(
        self, cog: Any, mock_interaction: MagicMock, movie_item: JellyfinItem
    ) -> None:
        """Test command with type posts single suggestion."""
        cog.bot.jellyfin_service.get_random_item = AsyncMock(return_value=movie_item)

        await cog.suggest_command(mock_interaction, content_type="movie")

        mock_interaction.response.defer.assert_called_once()
        cog.bot.jellyfin_service.get_random_item.assert_called_once_with("Movie")
        mock_interaction.followup.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_handles_no_jellyfin_service(
        self, cog: Any, mock_interaction: MagicMock
    ) -> None:
        """Test command handles missing Jellyfin service."""
        cog.bot.jellyfin_service = None

        await cog.suggest_command(mock_interaction, content_type=None)

        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "not initialized" in call_args[0][0]


# =============================================================================
# Schedule Suggestions Tests
# =============================================================================


class TestScheduleSuggestions:
    """Tests for _schedule_suggestions method."""

    @pytest.fixture
    def cog(self, mock_bot) -> Any:
        """Create a test cog."""
        return create_suggestions_cog(mock_bot)

    def test_schedules_valid_times(self, cog: Any) -> None:
        """Test that valid times are scheduled."""
        cog.bot.config.jellyfin.schedule.suggestion_times = ["12:00", "20:00"]

        cog._schedule_suggestions()

        # Should add 2 jobs
        assert cog.scheduler.add_job.call_count == 2

    def test_skips_invalid_times(self, cog: Any) -> None:
        """Test that invalid times are skipped."""
        cog.bot.config.jellyfin.schedule.suggestion_times = ["12:00", "25:00", "20:00"]

        cog._schedule_suggestions()

        # Should only add 2 jobs (invalid time skipped)
        assert cog.scheduler.add_job.call_count == 2


# =============================================================================
# Cog Setup Tests
# =============================================================================


class TestCogSetup:
    """Test cog setup functions."""

    @pytest.mark.asyncio
    async def test_suggestions_cog_setup(self, mock_bot: MagicMock) -> None:
        """Test suggestions cog setup function."""
        from bot.cogs.jellyfin.suggestions import setup

        mock_bot.add_cog = AsyncMock()
        with patch("bot.cogs.jellyfin.suggestions.create_scheduler"):
            await setup(mock_bot)
        mock_bot.add_cog.assert_called_once()

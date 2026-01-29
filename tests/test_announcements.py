"""Unit tests for bot/cogs/jellyfin/announcements.py - Jellyfin Announcements cog.

Tests cover:
    - Embed creation for different content types
    - Content type display names and formatting
    - Test mode date display functionality
    - Time parsing for scheduled announcements
"""

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.services.jellyfin import JellyfinItem


# =============================================================================
# Helper function to create a mock AnnouncementsCog
# =============================================================================


def create_announcements_cog(
    mock_bot: MagicMock,
) -> Any:
    """Create a JellyfinAnnouncementsCog with mocked dependencies."""
    with patch("bot.cogs.jellyfin.announcements.create_scheduler"):
        from bot.cogs.jellyfin.announcements import JellyfinAnnouncementsCog

        cog = JellyfinAnnouncementsCog(mock_bot)
        # Create a mock jellyfin client
        cog.jellyfin = MagicMock()
        cog.jellyfin.get_item_url = MagicMock(
            side_effect=lambda id: f"http://jellyfin/item/{id}"
        )
        cog.jellyfin.get_item_image_url = MagicMock(
            side_effect=lambda id: f"http://jellyfin/image/{id}"
        )
        return cog


# =============================================================================
# Content Type Display Name Tests
# =============================================================================


class TestGetTypeDisplayName:
    """Tests for _get_type_display_name method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_announcements_cog(mock_bot)

    def test_movie_display_name(self, cog: Any) -> None:
        """Test display name for Movie type."""
        assert cog._get_type_display_name("Movie") == "Movies"

    def test_series_display_name(self, cog: Any) -> None:
        """Test display name for Series type."""
        assert cog._get_type_display_name("Series") == "TV Shows"

    def test_audio_display_name(self, cog: Any) -> None:
        """Test display name for Audio type."""
        assert cog._get_type_display_name("Audio") == "Music"

    def test_music_display_name(self, cog: Any) -> None:
        """Test display name for Music type (alias)."""
        assert cog._get_type_display_name("Music") == "Music"

    def test_episode_display_name(self, cog: Any) -> None:
        """Test display name for Episode type."""
        assert cog._get_type_display_name("Episode") == "Episodes"

    def test_unknown_type_passthrough(self, cog: Any) -> None:
        """Test unknown types pass through unchanged."""
        assert cog._get_type_display_name("Unknown") == "Unknown"


# =============================================================================
# Item Embed Creation Tests
# =============================================================================


class TestCreateItemEmbed:
    """Tests for _create_item_embed method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_announcements_cog(mock_bot)

    def test_creates_embed_with_title(
        self, cog: Any, jellyfin_movie: JellyfinItem
    ) -> None:
        """Test embed has correct title."""
        embed = cog._create_item_embed(jellyfin_movie)

        assert embed.title == jellyfin_movie.display_title

    def test_creates_embed_with_url(
        self, cog: Any, jellyfin_movie: JellyfinItem
    ) -> None:
        """Test embed has correct URL."""
        embed = cog._create_item_embed(jellyfin_movie)

        assert embed.url == f"http://jellyfin/item/{jellyfin_movie.id}"

    def test_creates_embed_with_description(
        self, cog: Any, jellyfin_movie: JellyfinItem
    ) -> None:
        """Test embed includes overview as description."""
        embed = cog._create_item_embed(jellyfin_movie)

        assert embed.description == jellyfin_movie.overview

    def test_creates_embed_with_thumbnail(
        self, cog: Any, jellyfin_movie: JellyfinItem
    ) -> None:
        """Test embed has thumbnail."""
        embed = cog._create_item_embed(jellyfin_movie)

        assert embed.thumbnail is not None
        assert embed.thumbnail.url == f"http://jellyfin/image/{jellyfin_movie.id}"

    def test_truncates_long_description(self, cog: Any) -> None:
        """Test that long descriptions are truncated."""
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            overview="x" * 500,  # Longer than MAX_DESCRIPTION_LENGTH
        )

        embed = cog._create_item_embed(item)

        assert len(embed.description) <= 303  # 300 + "..."
        assert embed.description.endswith("...")

    def test_handles_no_overview(self, cog: Any) -> None:
        """Test embed handles missing overview."""
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            overview=None,
        )

        embed = cog._create_item_embed(item)

        assert embed.description is None


# =============================================================================
# Item Fields Tests
# =============================================================================


class TestAddItemFields:
    """Tests for _add_item_fields method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_announcements_cog(mock_bot)

    def test_adds_year_field(self, cog: Any) -> None:
        """Test year field is added for items with year."""
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            year=1999,
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        year_field = next((f for f in embed.fields if f.name == "Year"), None)
        assert year_field is not None
        assert year_field.value == "1999"

    def test_no_year_field_without_year(self, cog: Any) -> None:
        """Test year field is not added when year is missing."""
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        year_field = next((f for f in embed.fields if f.name == "Year"), None)
        assert year_field is None

    def test_adds_series_field_for_episode(self, cog: Any) -> None:
        """Test series field is added for episodes."""
        item = JellyfinItem(
            id="test",
            name="Pilot",
            item_type="Episode",
            series_name="Breaking Bad",
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        series_field = next((f for f in embed.fields if f.name == "Series"), None)
        assert series_field is not None
        assert series_field.value == "Breaking Bad"

    def test_no_series_field_for_non_episode(self, cog: Any) -> None:
        """Test series field is not added for non-episodes."""
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            series_name="Some Series",  # Should be ignored
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        series_field = next((f for f in embed.fields if f.name == "Series"), None)
        assert series_field is None

    def test_adds_artist_field_for_audio(self, cog: Any) -> None:
        """Test artist field is added for audio items."""
        item = JellyfinItem(
            id="test",
            name="Song",
            item_type="Audio",
            artists=["Queen", "David Bowie"],
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        artist_field = next((f for f in embed.fields if f.name == "Artist"), None)
        assert artist_field is not None
        assert artist_field.value == "Queen, David Bowie"

    def test_adds_album_field_for_audio(self, cog: Any) -> None:
        """Test album field is added for audio items."""
        item = JellyfinItem(
            id="test",
            name="Song",
            item_type="Audio",
            album="A Night at the Opera",
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        album_field = next((f for f in embed.fields if f.name == "Album"), None)
        assert album_field is not None
        assert album_field.value == "A Night at the Opera"


# =============================================================================
# Test Mode Date Display Tests
# =============================================================================


class TestTestModeDateDisplay:
    """Tests for date_created display in test mode."""

    def test_no_date_field_when_not_test_mode(self, mock_bot: MagicMock) -> None:
        """Test date field is not added in normal mode."""
        mock_bot.test_mode = False
        cog = create_announcements_cog(mock_bot)

        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            date_created=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        date_field = next(
            (f for f in embed.fields if f.name == "Added to Library"), None
        )
        assert date_field is None

    def test_date_field_added_in_test_mode(self, mock_bot: MagicMock) -> None:
        """Test date field is added in test mode."""
        mock_bot.test_mode = True
        cog = create_announcements_cog(mock_bot)

        dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            date_created=dt,
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        date_field = next(
            (f for f in embed.fields if f.name == "Added to Library"), None
        )
        assert date_field is not None
        # Should use Discord timestamp format
        assert f"<t:{int(dt.timestamp())}:F>" in date_field.value

    def test_no_date_field_in_test_mode_without_date(
        self, mock_bot: MagicMock
    ) -> None:
        """Test date field is not added in test mode when date is missing."""
        mock_bot.test_mode = True
        cog = create_announcements_cog(mock_bot)

        item = JellyfinItem(
            id="test",
            name="Test",
            item_type="Movie",
            date_created=None,
        )
        embed = discord.Embed()

        cog._add_item_fields(embed, item)

        date_field = next(
            (f for f in embed.fields if f.name == "Added to Library"), None
        )
        assert date_field is None


# =============================================================================
# Content Type Colors and Emojis Tests
# =============================================================================


class TestContentTypeConstants:
    """Tests for content type color and emoji constants."""

    def test_movie_color_is_blue(self) -> None:
        """Test Movie color is blue."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_COLORS

        assert CONTENT_TYPE_COLORS["Movie"] == discord.Color.blue()

    def test_series_color_is_green(self) -> None:
        """Test Series color is green."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_COLORS

        assert CONTENT_TYPE_COLORS["Series"] == discord.Color.green()

    def test_audio_color_is_purple(self) -> None:
        """Test Audio color is purple."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_COLORS

        assert CONTENT_TYPE_COLORS["Audio"] == discord.Color.purple()

    def test_movie_emoji(self) -> None:
        """Test Movie emoji is correct."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_EMOJI

        assert CONTENT_TYPE_EMOJI["Movie"] == "🎬"

    def test_series_emoji(self) -> None:
        """Test Series emoji is correct."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_EMOJI

        assert CONTENT_TYPE_EMOJI["Series"] == "📺"

    def test_audio_emoji(self) -> None:
        """Test Audio emoji is correct."""
        from bot.cogs.jellyfin.announcements import CONTENT_TYPE_EMOJI

        assert CONTENT_TYPE_EMOJI["Audio"] == "🎵"


# =============================================================================
# Announce New Content Tests
# =============================================================================


class TestAnnounceNewContent:
    """Tests for announce_new_content method."""

    @pytest.fixture
    def cog(self, mock_bot: MagicMock) -> Any:
        """Create a test cog."""
        return create_announcements_cog(mock_bot)

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_channel(
        self, cog: Any, mock_bot: MagicMock
    ) -> None:
        """Test returns 0 when channel is not found."""
        mock_bot.get_channel.return_value = None

        count = await cog.announce_new_content()

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_jellyfin(
        self, cog: Any, mock_discord_channel: MagicMock
    ) -> None:
        """Test returns 0 when jellyfin client is not initialized."""
        cog.jellyfin = None

        count = await cog.announce_new_content(channel=mock_discord_channel)

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_items(
        self, cog: Any, mock_discord_channel: MagicMock
    ) -> None:
        """Test returns 0 when no new items found."""
        cog.jellyfin.get_all_recent_items = AsyncMock(return_value={})

        count = await cog.announce_new_content(channel=mock_discord_channel)

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_item_count(
        self,
        cog: Any,
        mock_discord_channel: MagicMock,
        jellyfin_movie: JellyfinItem,
    ) -> None:
        """Test returns correct item count."""
        cog.jellyfin.get_all_recent_items = AsyncMock(
            return_value={"Movie": [jellyfin_movie]}
        )

        count = await cog.announce_new_content(channel=mock_discord_channel)

        assert count == 1

    @pytest.mark.asyncio
    async def test_sends_header_embed(
        self,
        cog: Any,
        mock_discord_channel: MagicMock,
        jellyfin_movie: JellyfinItem,
    ) -> None:
        """Test sends header embed first."""
        cog.jellyfin.get_all_recent_items = AsyncMock(
            return_value={"Movie": [jellyfin_movie]}
        )

        await cog.announce_new_content(channel=mock_discord_channel)

        # First call should be header embed
        first_call = mock_discord_channel.send.call_args_list[0]
        embed = first_call.kwargs["embed"]
        assert "New Content" in embed.title

    @pytest.mark.asyncio
    async def test_updates_last_announcement_time(
        self,
        cog: Any,
        mock_discord_channel: MagicMock,
        jellyfin_movie: JellyfinItem,
    ) -> None:
        """Test updates _last_announcement timestamp."""
        cog.jellyfin.get_all_recent_items = AsyncMock(
            return_value={"Movie": [jellyfin_movie]}
        )
        assert cog._last_announcement is None

        await cog.announce_new_content(channel=mock_discord_channel)

        assert cog._last_announcement is not None

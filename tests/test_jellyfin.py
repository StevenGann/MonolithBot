"""
Unit tests for bot/services/jellyfin.py - Jellyfin API client.

Tests cover:
    - JellyfinItem dataclass and display_title property
    - ServerInfo dataclass
    - JellyfinClient HTTP requests and error handling
    - Response parsing
    - URL building methods
"""

import re

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import aiohttp
from aioresponses import aioresponses

from bot.services.jellyfin import (
    JellyfinClient,
    JellyfinItem,
    ServerInfo,
    JellyfinError,
    JellyfinConnectionError,
    JellyfinAuthError,
)


# =============================================================================
# JellyfinItem Tests
# =============================================================================


class TestJellyfinItem:
    """Tests for JellyfinItem dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic JellyfinItem."""
        item = JellyfinItem(
            id="test-id",
            name="Test Item",
            item_type="Movie",
        )
        assert item.id == "test-id"
        assert item.name == "Test Item"
        assert item.item_type == "Movie"
        assert item.overview is None
        assert item.year is None
        assert item.date_created is None

    def test_full_creation(self) -> None:
        """Test creating JellyfinItem with all fields."""
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        item = JellyfinItem(
            id="test-id",
            name="The Matrix",
            item_type="Movie",
            overview="A computer hacker learns about reality.",
            year=1999,
            series_name=None,
            album=None,
            artists=None,
            date_created=dt,
        )
        assert item.year == 1999
        assert item.overview == "A computer hacker learns about reality."
        assert item.date_created == dt


class TestJellyfinItemDisplayTitle:
    """Tests for JellyfinItem.display_title property."""

    def test_movie_with_year(self) -> None:
        """Test display title for movie with year."""
        item = JellyfinItem(
            id="1",
            name="The Matrix",
            item_type="Movie",
            year=1999,
        )
        assert item.display_title == "The Matrix (1999)"

    def test_movie_without_year(self) -> None:
        """Test display title for movie without year."""
        item = JellyfinItem(
            id="1",
            name="Unknown Film",
            item_type="Movie",
        )
        assert item.display_title == "Unknown Film"

    def test_episode_with_series(self) -> None:
        """Test display title for episode shows series name."""
        item = JellyfinItem(
            id="1",
            name="Pilot",
            item_type="Episode",
            series_name="Breaking Bad",
        )
        assert item.display_title == "Breaking Bad - Pilot"

    def test_episode_without_series(self) -> None:
        """Test display title for episode without series name."""
        item = JellyfinItem(
            id="1",
            name="Unknown Episode",
            item_type="Episode",
        )
        assert item.display_title == "Unknown Episode"

    def test_audio_with_artists(self) -> None:
        """Test display title for audio with artists."""
        item = JellyfinItem(
            id="1",
            name="Bohemian Rhapsody",
            item_type="Audio",
            artists=["Queen"],
        )
        assert item.display_title == "Queen - Bohemian Rhapsody"

    def test_audio_with_multiple_artists(self) -> None:
        """Test display title for audio with multiple artists."""
        item = JellyfinItem(
            id="1",
            name="Under Pressure",
            item_type="Audio",
            artists=["Queen", "David Bowie"],
        )
        assert item.display_title == "Queen, David Bowie - Under Pressure"

    def test_audio_without_artists(self) -> None:
        """Test display title for audio without artists."""
        item = JellyfinItem(
            id="1",
            name="Unknown Track",
            item_type="Audio",
        )
        assert item.display_title == "Unknown Track"

    def test_series_with_year(self) -> None:
        """Test display title for series with year."""
        item = JellyfinItem(
            id="1",
            name="Breaking Bad",
            item_type="Series",
            year=2008,
        )
        assert item.display_title == "Breaking Bad (2008)"


# =============================================================================
# ServerInfo Tests
# =============================================================================


class TestServerInfo:
    """Tests for ServerInfo dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating ServerInfo with required fields."""
        info = ServerInfo(
            server_name="Monolith",
            version="10.8.13",
        )
        assert info.server_name == "Monolith"
        assert info.version == "10.8.13"
        assert info.operating_system is None

    def test_full_creation(self) -> None:
        """Test creating ServerInfo with all fields."""
        info = ServerInfo(
            server_name="Monolith",
            version="10.8.13",
            operating_system="Linux",
        )
        assert info.operating_system == "Linux"


# =============================================================================
# JellyfinClient Initialization Tests
# =============================================================================


class TestJellyfinClientInit:
    """Tests for JellyfinClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )
        assert client.base_url == "http://localhost:8096"
        assert client.api_key == "test-key"
        assert client._session is None

    def test_trailing_slash_removed(self) -> None:
        """Test that trailing slashes are removed from base URL."""
        client = JellyfinClient(
            base_url="http://localhost:8096/",
            api_key="test-key",
        )
        assert client.base_url == "http://localhost:8096"


# =============================================================================
# JellyfinClient URL Building Tests
# =============================================================================


class TestJellyfinClientUrls:
    """Tests for JellyfinClient URL building methods."""

    @pytest.fixture
    def client(self) -> JellyfinClient:
        """Create a test client."""
        return JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )

    def test_get_item_image_url_default(self, client: JellyfinClient) -> None:
        """Test building image URL with defaults."""
        url = client.get_item_image_url("item-123")
        assert url == "http://localhost:8096/Items/item-123/Images/Primary?maxWidth=400"

    def test_get_item_image_url_custom(self, client: JellyfinClient) -> None:
        """Test building image URL with custom parameters."""
        url = client.get_item_image_url(
            "item-123",
            image_type="Backdrop",
            max_width=800,
        )
        assert url == "http://localhost:8096/Items/item-123/Images/Backdrop?maxWidth=800"

    def test_get_item_url(self, client: JellyfinClient) -> None:
        """Test building item web UI URL."""
        url = client.get_item_url("item-123")
        assert url == "http://localhost:8096/web/index.html#!/details?id=item-123"

    def test_get_recently_added_url_movie(self, client: JellyfinClient) -> None:
        """Test building recently added URL for movies."""
        url = client.get_recently_added_url("Movie")
        assert url == (
            "http://localhost:8096/web/index.html#!/list.html"
            "?type=Movie&sortBy=DateCreated&sortOrder=Descending"
        )

    def test_get_recently_added_url_series(self, client: JellyfinClient) -> None:
        """Test building recently added URL for TV series."""
        url = client.get_recently_added_url("Series")
        assert url == (
            "http://localhost:8096/web/index.html#!/list.html"
            "?type=Series&sortBy=DateCreated&sortOrder=Descending"
        )

    def test_get_recently_added_url_audio(self, client: JellyfinClient) -> None:
        """Test building recently added URL for audio."""
        url = client.get_recently_added_url("Audio")
        assert url == (
            "http://localhost:8096/web/index.html#!/list.html"
            "?type=Audio&sortBy=DateCreated&sortOrder=Descending"
        )

    def test_get_recently_added_url_music_alias(self, client: JellyfinClient) -> None:
        """Test that Music maps to Audio type in URL."""
        url = client.get_recently_added_url("Music")
        assert url == (
            "http://localhost:8096/web/index.html#!/list.html"
            "?type=Audio&sortBy=DateCreated&sortOrder=Descending"
        )

    def test_get_recently_added_url_unknown_passthrough(
        self, client: JellyfinClient
    ) -> None:
        """Test that unknown content types pass through unchanged."""
        url = client.get_recently_added_url("Unknown")
        assert url == (
            "http://localhost:8096/web/index.html#!/list.html"
            "?type=Unknown&sortBy=DateCreated&sortOrder=Descending"
        )


# =============================================================================
# JellyfinClient HTTP Tests
# =============================================================================


class TestJellyfinClientHttp:
    """Tests for JellyfinClient HTTP operations."""

    @pytest.fixture
    def client(self) -> JellyfinClient:
        """Create a test client."""
        return JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_check_health_success(self, client: JellyfinClient) -> None:
        """Test successful health check."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={
                    "ServerName": "Test Server",
                    "Version": "10.8.13",
                    "OperatingSystem": "Linux",
                },
            )

            info = await client.check_health()

            assert info.server_name == "Test Server"
            assert info.version == "10.8.13"
            assert info.operating_system == "Linux"

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_default_values(self, client: JellyfinClient) -> None:
        """Test health check with missing response fields."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={},
            )

            info = await client.check_health()

            assert info.server_name == "Jellyfin"
            assert info.version == "Unknown"
            assert info.operating_system is None

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_auth_error_401(self, client: JellyfinClient) -> None:
        """Test health check returns auth error on 401."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                status=401,
            )

            with pytest.raises(JellyfinAuthError) as exc_info:
                await client.check_health()

            assert "Invalid API key" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_auth_error_403(self, client: JellyfinClient) -> None:
        """Test health check returns auth error on 403."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                status=403,
            )

            with pytest.raises(JellyfinAuthError) as exc_info:
                await client.check_health()

            assert "Access forbidden" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_api_error(self, client: JellyfinClient) -> None:
        """Test health check returns error on 500."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                status=500,
                body="Internal Server Error",
            )

            with pytest.raises(JellyfinError) as exc_info:
                await client.check_health()

            assert "API error 500" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_check_health_connection_error(self, client: JellyfinClient) -> None:
        """Test health check returns connection error when unreachable."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                exception=aiohttp.ClientConnectorError(
                    MagicMock(), OSError("Connection refused")
                ),
            )

            with pytest.raises(JellyfinConnectionError) as exc_info:
                await client.check_health()

            assert "Cannot connect to Jellyfin" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_get_recent_items_success(self, client: JellyfinClient) -> None:
        """Test getting recent items successfully."""
        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Name": "Test Movie",
                            "Type": "Movie",
                            "ProductionYear": 2024,
                            "Overview": "A test movie.",
                            # Set date_created to "now" so it passes the filter
                            "DateCreated": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%S.0000000Z"
                            ),
                        }
                    ],
                    "TotalRecordCount": 1,
                },
            )

            items = await client.get_recent_items("Movie", hours=24)

            assert len(items) == 1
            assert items[0].id == "movie-1"
            assert items[0].name == "Test Movie"
            assert items[0].item_type == "Movie"
            assert items[0].year == 2024
            assert items[0].overview == "A test movie."
            assert items[0].date_created is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_recent_items_filters_old_items(self, client: JellyfinClient) -> None:
        """Test that old items are filtered out client-side."""
        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Name": "Recent Movie",
                            "Type": "Movie",
                            # Recent: within 24 hours
                            "DateCreated": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%S.0000000Z"
                            ),
                        },
                        {
                            "Id": "movie-2",
                            "Name": "Old Movie",
                            "Type": "Movie",
                            # Old: 48 hours ago (outside 24-hour window)
                            "DateCreated": (
                                datetime.now(timezone.utc) - timedelta(hours=48)
                            ).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                        },
                    ],
                    "TotalRecordCount": 2,
                },
            )

            items = await client.get_recent_items("Movie", hours=24)

            # Only the recent movie should be included
            assert len(items) == 1
            assert items[0].name == "Recent Movie"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_recent_items_inherits_date_from_previous(
        self, client: JellyfinClient
    ) -> None:
        """Test that items without date_created inherit from previous item."""
        recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Name": "Movie With Date",
                            "Type": "Movie",
                            "DateCreated": recent_date,
                        },
                        {
                            "Id": "movie-2",
                            "Name": "Movie Without Date",
                            "Type": "Movie",
                            # No DateCreated - should inherit from movie-1
                        },
                    ],
                    "TotalRecordCount": 2,
                },
            )

            items = await client.get_recent_items("Movie", hours=24)

            # Both movies should be included (second inherits date from first)
            assert len(items) == 2
            assert items[0].name == "Movie With Date"
            assert items[1].name == "Movie Without Date"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_recent_items_skips_undated_at_start(
        self, client: JellyfinClient
    ) -> None:
        """Test that items without date_created at start are skipped."""
        recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Name": "First Movie Without Date",
                            "Type": "Movie",
                            # No DateCreated and no previous item - should be skipped
                        },
                        {
                            "Id": "movie-2",
                            "Name": "Movie With Date",
                            "Type": "Movie",
                            "DateCreated": recent_date,
                        },
                        {
                            "Id": "movie-3",
                            "Name": "Third Movie Without Date",
                            "Type": "Movie",
                            # No DateCreated but previous item has date - should inherit
                        },
                    ],
                    "TotalRecordCount": 3,
                },
            )

            items = await client.get_recent_items("Movie", hours=24)

            # First item skipped (no date, nothing to inherit)
            # Second and third included (third inherits from second)
            assert len(items) == 2
            assert items[0].name == "Movie With Date"
            assert items[1].name == "Third Movie Without Date"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_recent_items_empty(self, client: JellyfinClient) -> None:
        """Test getting recent items when none exist."""
        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [],
                    "TotalRecordCount": 0,
                },
            )

            items = await client.get_recent_items("Movie", hours=24)

            assert len(items) == 0

        await client.close()

    @pytest.mark.asyncio
    async def test_get_all_recent_items(self, client: JellyfinClient) -> None:
        """Test getting recent items for multiple content types."""
        recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        with aioresponses() as mocked:
            # Mock all three requests (Movie, Series, Audio)
            # aioresponses will handle them in order
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "m1",
                            "Name": "Movie 1",
                            "Type": "Movie",
                            "DateCreated": recent_date,
                        }
                    ],
                },
            )
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "s1",
                            "Name": "Series 1",
                            "Type": "Series",
                            "DateCreated": recent_date,
                        }
                    ],
                },
            )
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={"Items": []},
            )

            results = await client.get_all_recent_items(
                content_types=["Movie", "Series", "Audio"],
                hours=24,
            )

            assert "Movie" in results
            assert "Series" in results
            # Audio should not be in results since it's empty
            assert "Audio" not in results
            assert len(results["Movie"]) == 1
            assert len(results["Series"]) == 1

        await client.close()


# =============================================================================
# JellyfinClient Content Type Mapping Tests
# =============================================================================


class TestJellyfinClientContentTypeMapping:
    """Tests for content type mapping."""

    @pytest.fixture
    def client(self) -> JellyfinClient:
        """Create a test client."""
        return JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )

    def test_map_movie(self, client: JellyfinClient) -> None:
        """Test mapping Movie type."""
        assert client._map_content_type("Movie") == "Movie"

    def test_map_series(self, client: JellyfinClient) -> None:
        """Test mapping Series type."""
        assert client._map_content_type("Series") == "Series"

    def test_map_audio(self, client: JellyfinClient) -> None:
        """Test mapping Audio type."""
        assert client._map_content_type("Audio") == "Audio"

    def test_map_music_alias(self, client: JellyfinClient) -> None:
        """Test Music maps to Audio."""
        assert client._map_content_type("Music") == "Audio"

    def test_map_unknown_passthrough(self, client: JellyfinClient) -> None:
        """Test unknown types pass through unchanged."""
        assert client._map_content_type("Unknown") == "Unknown"


# =============================================================================
# JellyfinClient Date Parsing Tests
# =============================================================================


class TestJellyfinClientDateParsing:
    """Tests for date parsing in item responses."""

    @pytest.fixture
    def client(self) -> JellyfinClient:
        """Create a test client."""
        return JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )

    def test_parse_standard_date(self, client: JellyfinClient) -> None:
        """Test parsing standard Jellyfin date format."""
        data = {
            "Id": "test",
            "Name": "Test",
            "Type": "Movie",
            "DateCreated": "2024-01-15T10:30:00.0000000Z",
        }
        item = client._parse_item(data)
        assert item.date_created is not None
        assert item.date_created.year == 2024
        assert item.date_created.month == 1
        assert item.date_created.day == 15
        assert item.date_created.hour == 10
        assert item.date_created.minute == 30

    def test_parse_date_with_7_decimal_places(self, client: JellyfinClient) -> None:
        """Test parsing date with 7 decimal places (Jellyfin format)."""
        data = {
            "Id": "test",
            "Name": "Test",
            "Type": "Movie",
            "DateCreated": "2024-01-15T10:30:00.1234567Z",
        }
        item = client._parse_item(data)
        assert item.date_created is not None

    def test_parse_date_missing(self, client: JellyfinClient) -> None:
        """Test parsing item without date."""
        data = {
            "Id": "test",
            "Name": "Test",
            "Type": "Movie",
        }
        item = client._parse_item(data)
        assert item.date_created is None

    def test_parse_date_invalid(self, client: JellyfinClient) -> None:
        """Test parsing item with invalid date (should not raise)."""
        data = {
            "Id": "test",
            "Name": "Test",
            "Type": "Movie",
            "DateCreated": "invalid-date",
        }
        # Should not raise, just set date_created to None
        item = client._parse_item(data)
        assert item.date_created is None


# =============================================================================
# JellyfinClient Session Management Tests
# =============================================================================


class TestJellyfinClientSession:
    """Tests for session management."""

    @pytest.mark.asyncio
    async def test_session_lazy_init(self) -> None:
        """Test that session is lazily initialized."""
        client = JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )
        assert client._session is None

        # Access session property
        session = client.session
        assert session is not None
        assert client._session is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        """Test closing the session."""
        client = JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )
        # Create a session
        _ = client.session
        assert client._session is not None

        await client.close()
        assert client._session.closed

    @pytest.mark.asyncio
    async def test_close_without_session(self) -> None:
        """Test closing when session was never created."""
        client = JellyfinClient(
            base_url="http://localhost:8096",
            api_key="test-key",
        )
        # Should not raise
        await client.close()

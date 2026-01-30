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
    JellyfinService,
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
        assert (
            url == "http://localhost:8096/Items/item-123/Images/Backdrop?maxWidth=800"
        )

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
    async def test_get_recent_items_filters_old_items(
        self, client: JellyfinClient
    ) -> None:
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

    @pytest.mark.asyncio
    async def test_get_random_item_success(self, client: JellyfinClient) -> None:
        """Test getting a random item."""
        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "random-movie",
                            "Name": "Random Movie",
                            "Type": "Movie",
                            "ProductionYear": 2024,
                        }
                    ],
                    "TotalRecordCount": 1,
                },
            )

            item = await client.get_random_item("Movie")

            assert item is not None
            assert item.id == "random-movie"
            assert item.name == "Random Movie"
            assert item.item_type == "Movie"
            assert item.year == 2024

        await client.close()

    @pytest.mark.asyncio
    async def test_get_random_item_empty(self, client: JellyfinClient) -> None:
        """Test getting a random item when library is empty."""
        with aioresponses() as mocked:
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [],
                    "TotalRecordCount": 0,
                },
            )

            item = await client.get_random_item("Movie")

            assert item is None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_random_items_by_type(self, client: JellyfinClient) -> None:
        """Test getting random items for multiple content types."""
        with aioresponses() as mocked:
            # Mock responses for each type
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Name": "Random Movie",
                            "Type": "Movie",
                        }
                    ],
                },
            )
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={
                    "Items": [
                        {
                            "Id": "series-1",
                            "Name": "Random Series",
                            "Type": "Series",
                        }
                    ],
                },
            )
            mocked.get(
                re.compile(r"^http://localhost:8096/Items\?.*"),
                payload={"Items": []},  # No albums
            )

            results = await client.get_random_items_by_type(
                ["Movie", "Series", "MusicAlbum"]
            )

            assert "Movie" in results
            assert "Series" in results
            assert "MusicAlbum" not in results  # Empty
            assert results["Movie"].name == "Random Movie"
            assert results["Series"].name == "Random Series"

        await client.close()


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

    def test_map_music_album(self, client: JellyfinClient) -> None:
        """Test MusicAlbum type mapping."""
        assert client._map_content_type("MusicAlbum") == "MusicAlbum"

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


# =============================================================================
# JellyfinService Tests
# =============================================================================


class TestJellyfinServiceInit:
    """Tests for JellyfinService initialization."""

    def test_basic_init(self) -> None:
        """Test basic initialization with single URL."""
        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )
        assert service.urls == ["http://localhost:8096"]
        assert service.api_key == "test-key"
        assert service._active_url is None
        assert service._client is None

    def test_multiple_urls(self) -> None:
        """Test initialization with multiple URLs."""
        service = JellyfinService(
            urls=["http://primary:8096", "http://backup:8096"],
            api_key="test-key",
        )
        assert len(service.urls) == 2
        assert service.urls[0] == "http://primary:8096"
        assert service.urls[1] == "http://backup:8096"

    def test_trailing_slash_removed(self) -> None:
        """Test that trailing slashes are removed from URLs."""
        service = JellyfinService(
            urls=["http://localhost:8096/", "http://backup:8096///"],
            api_key="test-key",
        )
        assert service.urls[0] == "http://localhost:8096"
        assert service.urls[1] == "http://backup:8096"

    def test_active_url_property_none(self) -> None:
        """Test active_url property returns None before resolution."""
        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )
        assert service.active_url is None

    def test_active_url_property_after_set(self) -> None:
        """Test active_url property returns the cached URL."""
        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )
        service._active_url = "http://localhost:8096"
        assert service.active_url == "http://localhost:8096"


class TestJellyfinServiceResolveUrl:
    """Tests for JellyfinService.resolve_url() failover logic."""

    @pytest.mark.asyncio
    async def test_resolve_single_url_success(self) -> None:
        """Test resolving with a single working URL."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://localhost:8096"],
                api_key="test-key",
            )
            url = await service.resolve_url()

            assert url == "http://localhost:8096"
            assert service.active_url == "http://localhost:8096"
            assert service._client is not None

            await service.close()

    @pytest.mark.asyncio
    async def test_resolve_first_url_preferred(self) -> None:
        """Test that the first URL is used when all URLs work."""
        with aioresponses() as mocked:
            mocked.get(
                "http://primary:8096/System/Info",
                payload={"ServerName": "Primary", "Version": "10.8.0"},
            )
            # Backup should not be called

            service = JellyfinService(
                urls=["http://primary:8096", "http://backup:8096"],
                api_key="test-key",
            )
            url = await service.resolve_url()

            assert url == "http://primary:8096"
            assert service.active_url == "http://primary:8096"

            await service.close()

    @pytest.mark.asyncio
    async def test_failover_to_second_url(self) -> None:
        """Test failover to second URL when first fails."""
        with aioresponses() as mocked:
            mocked.get(
                "http://primary:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )
            mocked.get(
                "http://backup:8096/System/Info",
                payload={"ServerName": "Backup", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://primary:8096", "http://backup:8096"],
                api_key="test-key",
            )
            url = await service.resolve_url()

            assert url == "http://backup:8096"
            assert service.active_url == "http://backup:8096"

            await service.close()

    @pytest.mark.asyncio
    async def test_failover_to_third_url(self) -> None:
        """Test failover to third URL when first two fail."""
        with aioresponses() as mocked:
            mocked.get(
                "http://primary:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )
            mocked.get(
                "http://backup1:8096/System/Info",
                status=500,
            )
            mocked.get(
                "http://backup2:8096/System/Info",
                payload={"ServerName": "Backup2", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=[
                    "http://primary:8096",
                    "http://backup1:8096",
                    "http://backup2:8096",
                ],
                api_key="test-key",
            )
            url = await service.resolve_url()

            assert url == "http://backup2:8096"
            assert service.active_url == "http://backup2:8096"

            await service.close()

    @pytest.mark.asyncio
    async def test_all_urls_fail_raises_error(self) -> None:
        """Test that JellyfinConnectionError is raised when all URLs fail."""
        with aioresponses() as mocked:
            mocked.get(
                "http://primary:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )
            mocked.get(
                "http://backup:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )

            service = JellyfinService(
                urls=["http://primary:8096", "http://backup:8096"],
                api_key="test-key",
            )

            with pytest.raises(JellyfinConnectionError) as exc_info:
                await service.resolve_url()

            assert "All Jellyfin URLs failed" in str(exc_info.value)

            await service.close()

    @pytest.mark.asyncio
    async def test_empty_urls_raises_error(self) -> None:
        """Test that JellyfinError is raised when no URLs configured."""
        service = JellyfinService(
            urls=[],
            api_key="test-key",
        )

        with pytest.raises(JellyfinError) as exc_info:
            await service.resolve_url()

        assert "No Jellyfin URLs configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resolve_caches_client(self) -> None:
        """Test that resolve_url caches the client for reuse."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://localhost:8096"],
                api_key="test-key",
            )

            await service.resolve_url()
            first_client = service._client

            # Manually call _ensure_client to verify caching
            client = await service._ensure_client()
            assert client is first_client

            await service.close()

    @pytest.mark.asyncio
    async def test_resolve_closes_old_client_on_switch(self) -> None:
        """Test that old client is closed when switching URLs."""
        with aioresponses() as mocked:
            # First call - primary works
            mocked.get(
                "http://primary:8096/System/Info",
                payload={"ServerName": "Primary", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://primary:8096", "http://backup:8096"],
                api_key="test-key",
            )

            await service.resolve_url()
            first_client = service._client

            # Second call - primary fails, backup works
            mocked.get(
                "http://primary:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )
            mocked.get(
                "http://backup:8096/System/Info",
                payload={"ServerName": "Backup", "Version": "10.8.0"},
            )

            await service.resolve_url()
            second_client = service._client

            assert first_client is not second_client
            assert first_client._session.closed

            await service.close()


class TestJellyfinServiceCheckHealth:
    """Tests for JellyfinService.check_health() behavior."""

    @pytest.mark.asyncio
    async def test_check_health_returns_server_info(self) -> None:
        """Test that check_health returns ServerInfo."""
        with aioresponses() as mocked:
            # resolve_url call
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0", "Id": "server-123"},
            )
            # Actual health check call
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0", "Id": "server-123"},
            )

            service = JellyfinService(
                urls=["http://localhost:8096"],
                api_key="test-key",
            )
            info = await service.check_health()

            assert info.server_name == "Test"
            assert info.version == "10.8.0"

            await service.close()

    @pytest.mark.asyncio
    async def test_check_health_always_starts_from_top(self) -> None:
        """Test that health check always re-checks from primary URL."""
        with aioresponses() as mocked:
            # First resolve - primary fails, backup works
            mocked.get(
                "http://primary:8096/System/Info",
                exception=aiohttp.ClientError("Connection refused"),
            )
            mocked.get(
                "http://backup:8096/System/Info",
                payload={"ServerName": "Backup", "Version": "10.8.0"},
            )
            mocked.get(
                "http://backup:8096/System/Info",
                payload={"ServerName": "Backup", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://primary:8096", "http://backup:8096"],
                api_key="test-key",
            )

            # First health check - ends up on backup
            await service.check_health()
            assert service.active_url == "http://backup:8096"

            # Second resolve - primary recovered
            mocked.get(
                "http://primary:8096/System/Info",
                payload={"ServerName": "Primary", "Version": "10.8.0"},
            )
            mocked.get(
                "http://primary:8096/System/Info",
                payload={"ServerName": "Primary", "Version": "10.8.0"},
            )

            # Second health check - should switch back to primary
            await service.check_health()
            assert service.active_url == "http://primary:8096"

            await service.close()


class TestJellyfinServiceUrlBuilders:
    """Tests for JellyfinService URL builder methods."""

    def test_get_item_url_uses_active_url(self) -> None:
        """Test get_item_url uses cached active URL."""
        service = JellyfinService(
            urls=["http://primary:8096", "http://backup:8096"],
            api_key="test-key",
        )
        service._active_url = "http://backup:8096"

        url = service.get_item_url("item-123")
        assert "http://backup:8096" in url
        assert "item-123" in url

    def test_get_item_url_falls_back_to_primary(self) -> None:
        """Test get_item_url falls back to first URL when no active URL."""
        service = JellyfinService(
            urls=["http://primary:8096", "http://backup:8096"],
            api_key="test-key",
        )

        url = service.get_item_url("item-123")
        assert "http://primary:8096" in url

    def test_get_item_image_url_uses_active_url(self) -> None:
        """Test get_item_image_url uses cached active URL."""
        service = JellyfinService(
            urls=["http://primary:8096", "http://backup:8096"],
            api_key="test-key",
        )
        service._active_url = "http://backup:8096"

        url = service.get_item_image_url("item-123")
        assert "http://backup:8096" in url
        assert "item-123" in url
        assert "Primary" in url  # Default image type

    def test_get_recently_added_url_uses_active_url(self) -> None:
        """Test get_recently_added_url uses cached active URL."""
        service = JellyfinService(
            urls=["http://primary:8096", "http://backup:8096"],
            api_key="test-key",
        )
        service._active_url = "http://backup:8096"

        url = service.get_recently_added_url("Movie")
        assert "http://backup:8096" in url
        assert "Movie" in url


class TestJellyfinServiceDelegatedMethods:
    """Tests for JellyfinService delegated API methods."""

    @pytest.mark.asyncio
    async def test_get_recent_items_delegates_to_client(self) -> None:
        """Test that get_recent_items delegates to the underlying client."""
        from unittest.mock import AsyncMock

        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )

        # Set up a mock client
        mock_client = MagicMock()
        mock_client.get_recent_items = AsyncMock(return_value=[])
        service._client = mock_client
        service._active_url = "http://localhost:8096"

        items = await service.get_recent_items("Movie", hours=24)

        assert items == []
        mock_client.get_recent_items.assert_called_once_with(
            "Movie", hours=24, limit=20
        )

    @pytest.mark.asyncio
    async def test_get_random_item_delegates_to_client(self) -> None:
        """Test that get_random_item delegates to the underlying client."""
        from unittest.mock import AsyncMock

        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )

        # Set up a mock client
        mock_client = MagicMock()
        mock_client.get_random_item = AsyncMock(return_value=None)
        service._client = mock_client
        service._active_url = "http://localhost:8096"

        item = await service.get_random_item("Movie")

        assert item is None
        mock_client.get_random_item.assert_called_once_with("Movie")

    @pytest.mark.asyncio
    async def test_get_all_recent_items_delegates_to_client(self) -> None:
        """Test that get_all_recent_items delegates to the underlying client."""
        from unittest.mock import AsyncMock

        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )

        # Set up a mock client
        mock_client = MagicMock()
        mock_client.get_all_recent_items = AsyncMock(return_value={"Movie": []})
        service._client = mock_client
        service._active_url = "http://localhost:8096"

        result = await service.get_all_recent_items(["Movie"], hours=24)

        assert result == {"Movie": []}
        mock_client.get_all_recent_items.assert_called_once_with(["Movie"], hours=24)

    @pytest.mark.asyncio
    async def test_get_random_items_by_type_delegates_to_client(self) -> None:
        """Test that get_random_items_by_type delegates to the underlying client."""
        from unittest.mock import AsyncMock

        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )

        # Set up a mock client
        mock_client = MagicMock()
        mock_client.get_random_items_by_type = AsyncMock(return_value={})
        service._client = mock_client
        service._active_url = "http://localhost:8096"

        result = await service.get_random_items_by_type(["Movie", "Series"])

        assert result == {}
        mock_client.get_random_items_by_type.assert_called_once_with(
            ["Movie", "Series"]
        )


class TestJellyfinServiceLifecycle:
    """Tests for JellyfinService lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_clears_state(self) -> None:
        """Test that close clears active URL and client."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0"},
            )

            service = JellyfinService(
                urls=["http://localhost:8096"],
                api_key="test-key",
            )

            await service.resolve_url()
            assert service._active_url is not None
            assert service._client is not None

            await service.close()

            assert service._active_url is None
            assert service._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self) -> None:
        """Test that close works when no client was created."""
        service = JellyfinService(
            urls=["http://localhost:8096"],
            api_key="test-key",
        )

        # Should not raise
        await service.close()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager support."""
        with aioresponses() as mocked:
            mocked.get(
                "http://localhost:8096/System/Info",
                payload={"ServerName": "Test", "Version": "10.8.0"},
            )

            async with JellyfinService(
                urls=["http://localhost:8096"],
                api_key="test-key",
            ) as service:
                await service.resolve_url()
                assert service._client is not None

            # After context exit, should be closed
            assert service._client is None
            assert service._active_url is None

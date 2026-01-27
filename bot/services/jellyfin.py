"""
Jellyfin API client for MonolithBot.

Provides async methods for:
- Server health checks
- Fetching recently added content (movies, series, music)
- Building image and web player URLs
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("monolithbot.jellyfin")


@dataclass
class JellyfinItem:
    """Represents a Jellyfin media item."""

    id: str
    name: str
    item_type: str
    overview: Optional[str] = None
    year: Optional[int] = None
    series_name: Optional[str] = None
    album: Optional[str] = None
    artists: Optional[list[str]] = None
    date_created: Optional[datetime] = None

    @property
    def display_title(self) -> str:
        """Get display title based on item type."""
        if self.item_type == "Episode" and self.series_name:
            return f"{self.series_name} - {self.name}"
        if self.item_type == "Audio" and self.artists:
            return f"{', '.join(self.artists)} - {self.name}"
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name


@dataclass
class ServerInfo:
    """Jellyfin server information."""

    server_name: str
    version: str
    operating_system: Optional[str] = None


class JellyfinError(Exception):
    """Base exception for Jellyfin API errors."""

    pass


class JellyfinConnectionError(JellyfinError):
    """Raised when unable to connect to Jellyfin server."""

    pass


class JellyfinAuthError(JellyfinError):
    """Raised when authentication fails."""

    pass


class JellyfinClient:
    """Async client for Jellyfin API."""

    def __init__(self, base_url: str, api_key: str):
        """
        Initialize Jellyfin client.

        Args:
            base_url: Jellyfin server URL (e.g., http://localhost:8096)
            api_key: Jellyfin API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "X-Emby-Token": self.api_key,
                    "Accept": "application/json",
                }
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make an API request to Jellyfin.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /System/Info)
            **kwargs: Additional arguments passed to aiohttp request

        Returns:
            JSON response as dict

        Raises:
            JellyfinConnectionError: If unable to connect
            JellyfinAuthError: If authentication fails
            JellyfinError: For other API errors
        """
        url = f"{self.base_url}{endpoint}"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == 401:
                    raise JellyfinAuthError("Invalid API key")
                if response.status == 403:
                    raise JellyfinAuthError("Access forbidden - check API key permissions")
                if response.status >= 400:
                    text = await response.text()
                    raise JellyfinError(f"API error {response.status}: {text}")

                if response.content_type == "application/json":
                    return await response.json()
                return {}

        except aiohttp.ClientConnectorError as e:
            raise JellyfinConnectionError(f"Cannot connect to Jellyfin at {self.base_url}: {e}")
        except aiohttp.ClientError as e:
            raise JellyfinError(f"HTTP error: {e}")

    async def check_health(self) -> ServerInfo:
        """
        Check if Jellyfin server is healthy and responding.

        Returns:
            ServerInfo with server details

        Raises:
            JellyfinConnectionError: If server is unreachable
            JellyfinError: If server returns an error
        """
        data = await self._request("GET", "/System/Info")

        return ServerInfo(
            server_name=data.get("ServerName", "Jellyfin"),
            version=data.get("Version", "Unknown"),
            operating_system=data.get("OperatingSystem"),
        )

    async def get_recent_items(
        self,
        item_type: str,
        hours: int = 24,
        limit: int = 20,
    ) -> list[JellyfinItem]:
        """
        Get recently added items of a specific type.

        Args:
            item_type: Type of item - "Movie", "Series", "Audio", "Episode"
            hours: How many hours back to look (default 24)
            limit: Maximum number of items to return (default 20)

        Returns:
            List of JellyfinItem objects
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "MinDateCreated": cutoff_str,
            "Limit": str(limit),
            "Fields": "Overview,DateCreated,ProductionYear,Artists,Album,SeriesName",
        }

        data = await self._request("GET", "/Items", params=params)
        items = data.get("Items", [])

        return [self._parse_item(item) for item in items]

    async def get_all_recent_items(
        self,
        content_types: list[str],
        hours: int = 24,
    ) -> dict[str, list[JellyfinItem]]:
        """
        Get recently added items for multiple content types.

        Args:
            content_types: List of content types (e.g., ["Movie", "Series", "Audio"])
            hours: How many hours back to look

        Returns:
            Dict mapping content type to list of items
        """
        results = {}

        for content_type in content_types:
            # Map user-friendly types to Jellyfin types
            jellyfin_type = self._map_content_type(content_type)
            items = await self.get_recent_items(jellyfin_type, hours=hours)
            if items:
                results[content_type] = items

        return results

    def _map_content_type(self, content_type: str) -> str:
        """Map config content type to Jellyfin item type."""
        mapping = {
            "Movie": "Movie",
            "Series": "Series",
            "Audio": "Audio",
            "Music": "Audio",
            "Episode": "Episode",
        }
        return mapping.get(content_type, content_type)

    def _parse_item(self, data: dict) -> JellyfinItem:
        """Parse Jellyfin API response into JellyfinItem."""
        date_created = None
        if data.get("DateCreated"):
            try:
                date_str = data["DateCreated"].replace("Z", "+00:00")
                date_created = datetime.fromisoformat(date_str)
            except (ValueError, TypeError):
                pass

        return JellyfinItem(
            id=data["Id"],
            name=data.get("Name", "Unknown"),
            item_type=data.get("Type", "Unknown"),
            overview=data.get("Overview"),
            year=data.get("ProductionYear"),
            series_name=data.get("SeriesName"),
            album=data.get("Album"),
            artists=data.get("Artists"),
            date_created=date_created,
        )

    def get_item_image_url(
        self,
        item_id: str,
        image_type: str = "Primary",
        max_width: int = 400,
    ) -> str:
        """
        Build URL for an item's image.

        Args:
            item_id: Jellyfin item ID
            image_type: Image type (Primary, Backdrop, Banner, etc.)
            max_width: Maximum image width for scaling

        Returns:
            Full URL to the image
        """
        return f"{self.base_url}/Items/{item_id}/Images/{image_type}?maxWidth={max_width}"

    def get_item_url(self, item_id: str) -> str:
        """
        Build URL to view/play an item in Jellyfin web UI.

        Args:
            item_id: Jellyfin item ID

        Returns:
            Full URL to the item in web UI
        """
        return f"{self.base_url}/web/index.html#!/details?id={item_id}"

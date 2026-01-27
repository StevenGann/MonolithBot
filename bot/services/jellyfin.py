"""
Jellyfin API client for MonolithBot.

This module provides an async HTTP client for interacting with the Jellyfin
media server API. It handles authentication, error handling, and data parsing
for the specific endpoints needed by MonolithBot.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Structured error hierarchy for different failure modes
    - Data classes for type-safe response handling

Jellyfin API Endpoints Used:
    - GET /System/Info - Server health and version info
    - GET /Items - Query library items with filters

Example:
    >>> from bot.services.jellyfin import JellyfinClient
    >>>
    >>> client = JellyfinClient(
    ...     base_url="http://localhost:8096",
    ...     api_key="your-api-key"
    ... )
    >>>
    >>> # Check server health
    >>> info = await client.check_health()
    >>> print(f"Connected to {info.server_name} v{info.version}")
    >>>
    >>> # Get recent movies
    >>> movies = await client.get_recent_items("Movie", hours=24)
    >>> for movie in movies:
    ...     print(f"  - {movie.display_title}")
    >>>
    >>> # Always close when done
    >>> await client.close()

See Also:
    - Jellyfin API docs: https://api.jellyfin.org/
    - bot.cogs.announcements: Uses this client for content announcements
    - bot.cogs.health: Uses this client for health monitoring
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp

# Module logger
logger = logging.getLogger("monolithbot.jellyfin")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class JellyfinItem:
    """
    Represents a media item from the Jellyfin library.

    This class normalizes the various item types (movies, episodes, songs)
    into a common structure for easier handling in Discord embeds.

    Attributes:
        id: Unique Jellyfin item identifier (used for URLs and images).
        name: Item name/title as shown in Jellyfin.
        item_type: Jellyfin item type - "Movie", "Episode", "Audio", "Series".
        overview: Plot summary or description (may be None or very long).
        year: Production/release year (None for episodes, music).
        series_name: Parent series name (only for Episodes).
        album: Album name (only for Audio items).
        artists: List of artist names (only for Audio items).
        date_created: When the item was added to the library (UTC).

    Example:
        >>> item = JellyfinItem(
        ...     id="abc123",
        ...     name="The Matrix",
        ...     item_type="Movie",
        ...     year=1999
        ... )
        >>> print(item.display_title)
        'The Matrix (1999)'
    """

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
        """
        Generate a formatted display title based on item type.

        Returns different formats depending on content type:
            - Episodes: "Series Name - Episode Name"
            - Audio: "Artist1, Artist2 - Song Name"
            - Movies/Series with year: "Title (2024)"
            - Fallback: Just the name

        Returns:
            Formatted string suitable for display in Discord embeds.
        """
        if self.item_type == "Episode" and self.series_name:
            return f"{self.series_name} - {self.name}"
        if self.item_type == "Audio" and self.artists:
            return f"{', '.join(self.artists)} - {self.name}"
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name


@dataclass
class ServerInfo:
    """
    Jellyfin server information from the /System/Info endpoint.

    Used primarily for health checks and status display.

    Attributes:
        server_name: User-configured server name (e.g., "Monolith").
        version: Jellyfin server version string (e.g., "10.8.13").
        operating_system: Server OS (e.g., "Linux", "Windows"). May be None
            depending on server configuration.
    """

    server_name: str
    version: str
    operating_system: Optional[str] = None


# =============================================================================
# Exceptions
# =============================================================================


class JellyfinError(Exception):
    """
    Base exception for all Jellyfin API errors.

    Catch this to handle any Jellyfin-related failure. For more specific
    handling, catch the subclasses instead.

    Example:
        >>> try:
        ...     await client.check_health()
        ... except JellyfinError as e:
        ...     print(f"Jellyfin error: {e}")
    """

    pass


class JellyfinConnectionError(JellyfinError):
    """
    Raised when unable to establish a connection to the Jellyfin server.

    This typically indicates:
        - Server is down or unreachable
        - Network connectivity issues
        - Incorrect URL configuration
        - Firewall blocking the connection

    Example:
        >>> try:
        ...     await client.check_health()
        ... except JellyfinConnectionError:
        ...     print("Server is offline!")
    """

    pass


class JellyfinAuthError(JellyfinError):
    """
    Raised when authentication with Jellyfin fails.

    This indicates:
        - Invalid API key
        - API key lacks required permissions
        - API key has been revoked

    Example:
        >>> try:
        ...     await client.check_health()
        ... except JellyfinAuthError:
        ...     print("Check your API key configuration")
    """

    pass


# =============================================================================
# Jellyfin API Client
# =============================================================================


class JellyfinClient:
    """
    Async HTTP client for the Jellyfin API.

    This client handles all communication with a Jellyfin server, including
    authentication, request/response handling, and error management.

    The client uses lazy session initialization - the aiohttp session is only
    created when the first request is made. Always call `close()` when done
    to properly release resources.

    Attributes:
        base_url: The Jellyfin server base URL (without trailing slash).
        api_key: The API key used for authentication.

    Example:
        >>> async with JellyfinClient(url, api_key) as client:
        ...     info = await client.check_health()
        ...     print(info.server_name)

        Or manually managing lifecycle:

        >>> client = JellyfinClient(url, api_key)
        >>> try:
        ...     info = await client.check_health()
        ... finally:
        ...     await client.close()
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        """
        Initialize the Jellyfin client.

        Args:
            base_url: Jellyfin server URL (e.g., "http://localhost:8096").
                Trailing slashes are automatically stripped.
            api_key: Jellyfin API key for authentication. Generate this in
                Jellyfin Dashboard → API Keys.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """
        Get or create the aiohttp session.

        Uses lazy initialization - the session is created on first access.
        If the session was closed, a new one is created.

        Returns:
            Configured aiohttp ClientSession with authentication headers.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    # Jellyfin uses X-Emby-Token for API key auth (Emby heritage)
                    "X-Emby-Token": self.api_key,
                    "Accept": "application/json",
                }
            )
        return self._session

    async def close(self) -> None:
        """
        Close the HTTP session and release resources.

        This should always be called when done with the client. Safe to call
        multiple times or if the session was never created.
        """
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the Jellyfin API.

        This is the core request method used by all public API methods.
        It handles authentication, error responses, and connection failures.

        Args:
            method: HTTP method ("GET", "POST", etc.).
            endpoint: API endpoint path (e.g., "/System/Info").
                Should start with a forward slash.
            **kwargs: Additional arguments passed to aiohttp's request method.
                Common: params (dict), json (dict), timeout (float).

        Returns:
            Parsed JSON response as a dictionary. Returns empty dict if
            the response is not JSON.

        Raises:
            JellyfinConnectionError: If unable to connect to the server.
            JellyfinAuthError: If authentication fails (401/403 response).
            JellyfinError: For other HTTP errors (4xx/5xx responses).
        """
        url = f"{self.base_url}{endpoint}"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                # Handle authentication errors
                if response.status == 401:
                    raise JellyfinAuthError("Invalid API key")
                if response.status == 403:
                    raise JellyfinAuthError(
                        "Access forbidden - check API key permissions"
                    )

                # Handle other HTTP errors
                if response.status >= 400:
                    text = await response.text()
                    raise JellyfinError(f"API error {response.status}: {text}")

                # Parse JSON response (if applicable)
                if response.content_type == "application/json":
                    return await response.json()
                return {}

        except aiohttp.ClientConnectorError as e:
            raise JellyfinConnectionError(
                f"Cannot connect to Jellyfin at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise JellyfinError(f"HTTP error: {e}")

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------

    async def check_health(self) -> ServerInfo:
        """
        Check if the Jellyfin server is healthy and responding.

        Makes a request to /System/Info to verify the server is online
        and retrieve basic server information.

        Returns:
            ServerInfo object with server name, version, and OS.

        Raises:
            JellyfinConnectionError: If the server is unreachable.
            JellyfinAuthError: If the API key is invalid.
            JellyfinError: If the server returns an error.

        Example:
            >>> info = await client.check_health()
            >>> print(f"Server: {info.server_name} v{info.version}")
            'Server: Monolith v10.8.13'
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

        Queries the Jellyfin library for items added within the specified
        time window, sorted by date added (newest first).

        Args:
            item_type: Jellyfin item type to query. Valid values:
                - "Movie": Feature films
                - "Series": TV series (the show itself, not episodes)
                - "Episode": Individual TV episodes
                - "Audio": Music tracks
            hours: How many hours back to look for new content.
                Default is 24 (one day).
            limit: Maximum number of items to return. Default is 20.
                Use to prevent overwhelming Discord with announcements.

        Returns:
            List of JellyfinItem objects, sorted newest first.
            Empty list if no items match the criteria.

        Example:
            >>> movies = await client.get_recent_items("Movie", hours=48)
            >>> for movie in movies:
            ...     print(f"Added: {movie.display_title}")
        """
        # Calculate cutoff timestamp in UTC
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "MinDateCreated": cutoff_str,
            "Limit": str(limit),
            # Request additional fields needed for display
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

        Convenience method that queries multiple content types and returns
        them grouped by type. Only types with results are included.

        Args:
            content_types: List of content types to query.
                Supports both Jellyfin types ("Movie", "Series", "Audio")
                and aliases ("Music" → "Audio").
            hours: How many hours back to look for new content.

        Returns:
            Dictionary mapping content type names to lists of items.
            Types with no results are omitted from the dict.

        Example:
            >>> results = await client.get_all_recent_items(
            ...     ["Movie", "Series", "Music"],
            ...     hours=24
            ... )
            >>> for content_type, items in results.items():
            ...     print(f"{content_type}: {len(items)} new items")
        """
        results: dict[str, list[JellyfinItem]] = {}

        for content_type in content_types:
            # Map user-friendly type names to Jellyfin API types
            jellyfin_type = self._map_content_type(content_type)
            items = await self.get_recent_items(jellyfin_type, hours=hours)
            if items:
                results[content_type] = items

        return results

    # -------------------------------------------------------------------------
    # URL Builders
    # -------------------------------------------------------------------------

    def get_item_image_url(
        self,
        item_id: str,
        image_type: str = "Primary",
        max_width: int = 400,
    ) -> str:
        """
        Build URL for an item's image.

        Constructs a URL to retrieve an item's image from Jellyfin.
        The image is automatically scaled to the specified width while
        maintaining aspect ratio.

        Args:
            item_id: Jellyfin item ID.
            image_type: Type of image to retrieve. Options:
                - "Primary": Main poster/cover art (default)
                - "Backdrop": Background/fanart image
                - "Banner": Wide banner image
                - "Thumb": Thumbnail image
            max_width: Maximum width in pixels for scaling.
                Height is calculated automatically to maintain aspect ratio.

        Returns:
            Full URL to the image that can be used in Discord embeds.

        Example:
            >>> url = client.get_item_image_url("abc123", max_width=300)
            >>> embed.set_thumbnail(url=url)
        """
        return (
            f"{self.base_url}/Items/{item_id}/Images/{image_type}"
            f"?maxWidth={max_width}"
        )

    def get_item_url(self, item_id: str) -> str:
        """
        Build URL to view/play an item in the Jellyfin web UI.

        Creates a direct link to the item's details page in Jellyfin,
        allowing users to click through from Discord to watch content.

        Args:
            item_id: Jellyfin item ID.

        Returns:
            Full URL to the item's page in the Jellyfin web interface.

        Example:
            >>> url = client.get_item_url("abc123")
            >>> embed = discord.Embed(title=movie.name, url=url)
        """
        return f"{self.base_url}/web/index.html#!/details?id={item_id}"

    # -------------------------------------------------------------------------
    # Private Helpers
    # -------------------------------------------------------------------------

    def _map_content_type(self, content_type: str) -> str:
        """
        Map user-friendly content type names to Jellyfin API types.

        Allows configuration to use friendlier names while translating
        to the actual Jellyfin item types for API queries.

        Args:
            content_type: Content type from configuration.

        Returns:
            Jellyfin item type string. If no mapping exists, returns
            the input unchanged (pass-through for unknown types).
        """
        mapping = {
            "Movie": "Movie",
            "Series": "Series",
            "Audio": "Audio",
            "Music": "Audio",  # Alias for user convenience
            "Episode": "Episode",
        }
        return mapping.get(content_type, content_type)

    def _parse_item(self, data: dict[str, Any]) -> JellyfinItem:
        """
        Parse a Jellyfin API item response into a JellyfinItem dataclass.

        Handles missing fields gracefully with defaults, and parses
        the ISO 8601 date string into a Python datetime.

        Args:
            data: Raw item dictionary from Jellyfin API response.

        Returns:
            Populated JellyfinItem instance.
        """
        # Parse the date string (handle Jellyfin's ISO format)
        date_created = None
        if data.get("DateCreated"):
            try:
                date_str = data["DateCreated"]
                # Jellyfin uses 'Z' suffix; convert to +00:00 for fromisoformat
                date_str = date_str.replace("Z", "+00:00")
                # Jellyfin can have 7 decimal places, but Python only handles 6
                # Truncate fractional seconds to 6 digits if present
                if "." in date_str:
                    # Split at the decimal point
                    base, frac_and_tz = date_str.split(".", 1)
                    # Find where the timezone starts (+ or -)
                    tz_start = -1
                    for i, char in enumerate(frac_and_tz):
                        if char in "+-":
                            tz_start = i
                            break
                    if tz_start > 0:
                        frac = frac_and_tz[:tz_start][:6]  # Truncate to 6 digits
                        tz = frac_and_tz[tz_start:]
                        date_str = f"{base}.{frac}{tz}"
                date_created = datetime.fromisoformat(date_str)
            except (ValueError, TypeError) as e:
                # Log but don't fail if date parsing fails
                logger.debug(f"Could not parse date: {data.get('DateCreated')} - {e}")

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

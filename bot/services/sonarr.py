"""
Sonarr API client and service for MonolithBot.

This module provides an async HTTP client for interacting with the Sonarr v3 API,
enabling the bot to look up and add TV series to the Sonarr library.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Structured error hierarchy for different failure modes
    - Data classes for type-safe response handling
    - Lookup by IMDB ID or TVDB ID

Architecture:
    - SonarrClient: Low-level HTTP client for a single Sonarr URL
    - SonarrService: High-level service that stores config and exposes clean methods

Sonarr API Endpoints Used:
    - GET /api/v3/series/lookup?term=imdb:{id}  - Look up series by IMDB ID
    - GET /api/v3/series/lookup?term=tvdb:{id}  - Look up series by TVDB ID
    - POST /api/v3/series                        - Add a series to the library

Example:
    >>> from bot.services.sonarr import SonarrService
    >>>
    >>> service = SonarrService(
    ...     url="http://sonarr:8989",
    ...     api_key="your-api-key",
    ...     root_folder_path="/tv",
    ...     quality_profile_id=1,
    ... )
    >>>
    >>> results = await service.lookup_by_imdb("tt0944947")
    >>> if results:
    ...     series = await service.add_series(results[0].raw)
    ...     print(f"Added: {series.title}")
    >>>
    >>> await service.close()

See Also:
    - Sonarr API docs: https://sonarr.tv/
    - bot.cogs.jellyfin.requests: Uses this service for content requests
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("monolithbot.sonarr")


# =============================================================================
# Exceptions
# =============================================================================


class SonarrError(Exception):
    """Base exception for all Sonarr-related errors."""
    pass


class SonarrConnectionError(SonarrError):
    """Raised when the Sonarr server cannot be reached."""
    pass


class SonarrAuthError(SonarrError):
    """Raised when the API key is invalid or missing."""
    pass


class SonarrNotFoundError(SonarrError):
    """Raised when a requested resource does not exist in Sonarr."""
    pass


class SonarrExistsError(SonarrError):
    """Raised when attempting to add a series that is already in the library."""

    def __init__(self, message: str, series: Optional["SonarrSeries"] = None) -> None:
        super().__init__(message)
        self.series = series


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SonarrSeries:
    """
    Represents a TV series from Sonarr's lookup or library.

    Attributes:
        title: Series title.
        year: First air year, or None if unknown.
        tvdb_id: The TV Database ID (required by Sonarr for adding).
        imdb_id: IMDB ID in tt-format, or None if not available.
        overview: Plot summary, or None if not available.
        remote_poster: URL to the series poster image, or None.
        raw: The full raw dict from the Sonarr API, used when posting back.
    """

    title: str
    year: Optional[int]
    tvdb_id: int
    imdb_id: Optional[str]
    overview: Optional[str]
    remote_poster: Optional[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _parse_series(data: dict[str, Any]) -> SonarrSeries:
    """Parse a Sonarr API series dict into a SonarrSeries dataclass."""
    images = data.get("images", [])
    poster_url = None
    for img in images:
        if img.get("coverType") == "poster":
            poster_url = img.get("remoteUrl") or img.get("url")
            break

    return SonarrSeries(
        title=data.get("title", "Unknown"),
        year=data.get("year") or None,
        tvdb_id=data["tvdbId"],
        imdb_id=data.get("imdbId") or None,
        overview=data.get("overview") or None,
        remote_poster=poster_url,
        raw=data,
    )


# =============================================================================
# Client
# =============================================================================


class SonarrClient:
    """
    Low-level async HTTP client for a single Sonarr instance.

    Uses lazy session initialization — the aiohttp session is created on
    the first request and reused for subsequent calls.

    Args:
        url: Base URL for the Sonarr instance (e.g. "http://sonarr:8989").
        api_key: Sonarr API key.
    """

    def __init__(self, url: str, api_key: str) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Api-Key": self._api_key, "Accept": "application/json"}
            )
        return self._session

    async def _lookup(self, term: str) -> list[SonarrSeries]:
        """
        Internal lookup helper.

        Args:
            term: Search term in Sonarr format, e.g. "imdb:tt0944947" or "tvdb:295759".

        Returns:
            List of SonarrSeries results.

        Raises:
            SonarrConnectionError: If the server is unreachable.
            SonarrAuthError: If the API key is invalid.
        """
        session = self._get_session()
        url = f"{self._url}/api/v3/series/lookup"
        params = {"term": term}

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 401:
                    raise SonarrAuthError("Invalid Sonarr API key")
                if resp.status == 404:
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return [_parse_series(item) for item in data]
        except aiohttp.ClientConnectorError as e:
            raise SonarrConnectionError(f"Cannot reach Sonarr at {self._url}: {e}") from e
        except aiohttp.ClientError as e:
            raise SonarrConnectionError(f"Sonarr request failed: {e}") from e

    async def lookup_by_imdb(self, imdb_id: str) -> list[SonarrSeries]:
        """
        Look up a series in Sonarr by IMDB ID.

        Args:
            imdb_id: IMDB ID in tt-format (e.g. "tt0944947").

        Returns:
            List of matching SonarrSeries objects (usually 0 or 1).
        """
        return await self._lookup(f"imdb:{imdb_id}")

    async def lookup_by_tvdb(self, tvdb_id: int) -> list[SonarrSeries]:
        """
        Look up a series in Sonarr by TVDB ID.

        Args:
            tvdb_id: Numeric TVDB ID (e.g. 295759).

        Returns:
            List of matching SonarrSeries objects (usually 0 or 1).
        """
        return await self._lookup(f"tvdb:{tvdb_id}")

    async def add_series(
        self,
        series_raw: dict[str, Any],
        root_folder_path: str,
        quality_profile_id: int,
    ) -> SonarrSeries:
        """
        Add a series to the Sonarr library.

        Takes the raw dict from a lookup result, augments it with the required
        library settings, and POSTs it to Sonarr.

        Args:
            series_raw: Raw series dict from a lookup (the SonarrSeries.raw field).
            root_folder_path: Filesystem path to the root TV folder.
            quality_profile_id: Sonarr quality profile ID to use.

        Returns:
            SonarrSeries representing the newly added entry.

        Raises:
            SonarrExistsError: If the series is already in the library.
            SonarrConnectionError: If the server is unreachable.
            SonarrAuthError: If the API key is invalid.
        """
        session = self._get_session()
        url = f"{self._url}/api/v3/series"

        payload = {
            **series_raw,
            "rootFolderPath": root_folder_path,
            "qualityProfileId": quality_profile_id,
            "monitored": True,
            "addOptions": {
                "monitor": "all",
                "searchForMissingEpisodes": True,
            },
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 401:
                    raise SonarrAuthError("Invalid Sonarr API key")
                if resp.status == 400:
                    body = await resp.text()
                    if "already" in body.lower() or "exists" in body.lower():
                        series = _parse_series(series_raw)
                        raise SonarrExistsError(
                            f"{series.title} is already in the Sonarr library", series=series
                        )
                    raise SonarrError(f"Sonarr rejected the request: {body}")
                resp.raise_for_status()
                data = await resp.json()
                return _parse_series(data)
        except aiohttp.ClientConnectorError as e:
            raise SonarrConnectionError(f"Cannot reach Sonarr at {self._url}: {e}") from e
        except aiohttp.ClientError as e:
            raise SonarrConnectionError(f"Sonarr request failed: {e}") from e

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# =============================================================================
# Service
# =============================================================================


class SonarrService:
    """
    High-level service for Sonarr interactions.

    Wraps SonarrClient and stores library configuration (root folder,
    quality profile) so callers don't need to pass them on every call.

    Args:
        url: Base URL for the Sonarr instance.
        api_key: Sonarr API key.
        root_folder_path: Default root folder path for adding series.
        quality_profile_id: Default quality profile ID for adding series.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        root_folder_path: str,
        quality_profile_id: int,
    ) -> None:
        self._client = SonarrClient(url=url, api_key=api_key)
        self._root_folder_path = root_folder_path
        self._quality_profile_id = quality_profile_id

    async def lookup_by_imdb(self, imdb_id: str) -> list[SonarrSeries]:
        """Look up a series by IMDB ID. Returns empty list if not found."""
        return await self._client.lookup_by_imdb(imdb_id)

    async def lookup_by_tvdb(self, tvdb_id: int) -> list[SonarrSeries]:
        """Look up a series by TVDB ID. Returns empty list if not found."""
        return await self._client.lookup_by_tvdb(tvdb_id)

    async def add_series(self, series_raw: dict[str, Any]) -> SonarrSeries:
        """
        Add a series using the stored root folder and quality profile.

        Args:
            series_raw: Raw dict from a lookup result (SonarrSeries.raw).

        Returns:
            The added SonarrSeries.

        Raises:
            SonarrExistsError: If the series is already in the library.
            SonarrConnectionError: If the server is unreachable.
        """
        return await self._client.add_series(
            series_raw=series_raw,
            root_folder_path=self._root_folder_path,
            quality_profile_id=self._quality_profile_id,
        )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self._client.close()

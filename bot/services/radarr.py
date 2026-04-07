"""
Radarr API client and service for MonolithBot.

This module provides an async HTTP client for interacting with the Radarr v3 API,
enabling the bot to look up and add movies to the Radarr library.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Structured error hierarchy for different failure modes
    - Data classes for type-safe response handling

Architecture:
    - RadarrClient: Low-level HTTP client for a single Radarr URL
    - RadarrService: High-level service that stores config and exposes clean methods

Radarr API Endpoints Used:
    - GET /api/v3/movie/lookup?term=imdb:{id} - Look up movie by IMDB ID
    - POST /api/v3/movie - Add a movie to the Radarr library

Example:
    >>> from bot.services.radarr import RadarrService
    >>>
    >>> service = RadarrService(
    ...     url="http://radarr:7878",
    ...     api_key="your-api-key",
    ...     root_folder_path="/movies",
    ...     quality_profile_id=1,
    ... )
    >>>
    >>> results = await service.lookup_movie("tt0133093")
    >>> if results:
    ...     movie = await service.add_movie(results[0].raw)
    ...     print(f"Added: {movie.title}")
    >>>
    >>> await service.close()

See Also:
    - Radarr API docs: https://radarr.video/docs/api/
    - bot.cogs.jellyfin.requests: Uses this service for content requests
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("monolithbot.radarr")


# =============================================================================
# Exceptions
# =============================================================================


class RadarrError(Exception):
    """Base exception for all Radarr-related errors."""
    pass


class RadarrConnectionError(RadarrError):
    """Raised when the Radarr server cannot be reached."""
    pass


class RadarrAuthError(RadarrError):
    """Raised when the API key is invalid or missing."""
    pass


class RadarrNotFoundError(RadarrError):
    """Raised when a requested resource does not exist in Radarr."""
    pass


class RadarrExistsError(RadarrError):
    """Raised when attempting to add a movie that is already in the library."""

    def __init__(self, message: str, movie: Optional["RadarrMovie"] = None) -> None:
        super().__init__(message)
        self.movie = movie


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RadarrMovie:
    """
    Represents a movie from Radarr's lookup or library.

    Attributes:
        title: Movie title.
        year: Release year, or None if unknown.
        tmdb_id: The Movie Database ID (required by Radarr for adding).
        imdb_id: IMDB ID in tt-format, or None if not available.
        overview: Plot summary, or None if not available.
        remote_poster: URL to the movie poster image, or None.
        raw: The full raw dict from the Radarr API, used when posting back.
    """

    title: str
    year: Optional[int]
    tmdb_id: int
    imdb_id: Optional[str]
    overview: Optional[str]
    remote_poster: Optional[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _parse_movie(data: dict[str, Any]) -> RadarrMovie:
    """Parse a Radarr API movie dict into a RadarrMovie dataclass."""
    images = data.get("images", [])
    poster_url = None
    for img in images:
        if img.get("coverType") == "poster":
            poster_url = img.get("remoteUrl") or img.get("url")
            break

    return RadarrMovie(
        title=data.get("title", "Unknown"),
        year=data.get("year") or None,
        tmdb_id=data["tmdbId"],
        imdb_id=data.get("imdbId") or None,
        overview=data.get("overview") or None,
        remote_poster=poster_url,
        raw=data,
    )


# =============================================================================
# Client
# =============================================================================


class RadarrClient:
    """
    Low-level async HTTP client for a single Radarr instance.

    Uses lazy session initialization — the aiohttp session is created on
    the first request and reused for subsequent calls.

    Args:
        url: Base URL for the Radarr instance (e.g. "http://radarr:7878").
        api_key: Radarr API key.
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

    async def lookup_movie(self, imdb_id: str) -> list[RadarrMovie]:
        """
        Look up a movie in Radarr by IMDB ID.

        Args:
            imdb_id: IMDB ID in tt-format (e.g. "tt0133093").

        Returns:
            List of matching RadarrMovie objects (usually 0 or 1).

        Raises:
            RadarrConnectionError: If the server is unreachable.
            RadarrAuthError: If the API key is invalid.
        """
        session = self._get_session()
        url = f"{self._url}/api/v3/movie/lookup"
        params = {"term": f"imdb:{imdb_id}"}

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 401:
                    raise RadarrAuthError("Invalid Radarr API key")
                if resp.status == 404:
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return [_parse_movie(item) for item in data]
        except aiohttp.ClientConnectorError as e:
            raise RadarrConnectionError(f"Cannot reach Radarr at {self._url}: {e}") from e
        except aiohttp.ClientError as e:
            raise RadarrConnectionError(f"Radarr request failed: {e}") from e

    async def add_movie(
        self,
        movie_raw: dict[str, Any],
        root_folder_path: str,
        quality_profile_id: int,
    ) -> RadarrMovie:
        """
        Add a movie to the Radarr library.

        Takes the raw dict from a lookup result, augments it with the required
        library settings, and POSTs it to Radarr.

        Args:
            movie_raw: Raw movie dict from lookup_movie (the RadarrMovie.raw field).
            root_folder_path: Filesystem path to the root movies folder.
            quality_profile_id: Radarr quality profile ID to use.

        Returns:
            RadarrMovie representing the newly added entry.

        Raises:
            RadarrExistsError: If the movie is already in the library.
            RadarrConnectionError: If the server is unreachable.
            RadarrAuthError: If the API key is invalid.
        """
        session = self._get_session()
        url = f"{self._url}/api/v3/movie"

        payload = {
            **movie_raw,
            "rootFolderPath": root_folder_path,
            "qualityProfileId": quality_profile_id,
            "monitored": True,
            "addOptions": {"searchForMovie": True},
        }

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 401:
                    raise RadarrAuthError("Invalid Radarr API key")
                if resp.status == 400:
                    body = await resp.text()
                    if "already" in body.lower() or "exists" in body.lower():
                        movie = _parse_movie(movie_raw)
                        raise RadarrExistsError(
                            f"{movie.title} is already in the Radarr library", movie=movie
                        )
                    raise RadarrError(f"Radarr rejected the request: {body}")
                resp.raise_for_status()
                data = await resp.json()
                return _parse_movie(data)
        except aiohttp.ClientConnectorError as e:
            raise RadarrConnectionError(f"Cannot reach Radarr at {self._url}: {e}") from e
        except aiohttp.ClientError as e:
            raise RadarrConnectionError(f"Radarr request failed: {e}") from e

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# =============================================================================
# Service
# =============================================================================


class RadarrService:
    """
    High-level service for Radarr interactions.

    Wraps RadarrClient and stores library configuration (root folder,
    quality profile) so callers don't need to pass them on every call.

    Args:
        url: Base URL for the Radarr instance.
        api_key: Radarr API key.
        root_folder_path: Default root folder path for adding movies.
        quality_profile_id: Default quality profile ID for adding movies.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        root_folder_path: str,
        quality_profile_id: int,
    ) -> None:
        self._client = RadarrClient(url=url, api_key=api_key)
        self._root_folder_path = root_folder_path
        self._quality_profile_id = quality_profile_id

    async def lookup_movie(self, imdb_id: str) -> list[RadarrMovie]:
        """Look up a movie by IMDB ID. Returns empty list if not found."""
        return await self._client.lookup_movie(imdb_id)

    async def add_movie(self, movie_raw: dict[str, Any]) -> RadarrMovie:
        """
        Add a movie using the stored root folder and quality profile.

        Args:
            movie_raw: Raw dict from a lookup result (RadarrMovie.raw).

        Returns:
            The added RadarrMovie.

        Raises:
            RadarrExistsError: If the movie is already in the library.
            RadarrConnectionError: If the server is unreachable.
        """
        return await self._client.add_movie(
            movie_raw=movie_raw,
            root_folder_path=self._root_folder_path,
            quality_profile_id=self._quality_profile_id,
        )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self._client.close()

"""
Organizr API client and service for MonolithBot.

This module provides an async HTTP client for the Organizr v2 REST API,
used for user provisioning in the registration feature.

Organizr is an HTPC/Homelab services organizer (https://github.com/causefx/Organizr).
Authentication is session-based: POST /api/v2/login then reuse the session cookie
for GET/POST /api/v2/users.

Endpoints used:
    - POST /api/v2/login - Authenticate (session cookie)
    - GET /api/v2/users - List users (check existence)
    - POST /api/v2/users - Create user (admin)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("monolithbot.organizr")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class OrganizrUser:
    """Represents a user in Organizr (id, username)."""

    id: int
    username: str


# =============================================================================
# Exceptions
# =============================================================================


class OrganizrError(Exception):
    """Base exception for Organizr API errors."""

    pass


class OrganizrConnectionError(OrganizrError):
    """Raised when unable to connect to the Organizr server."""

    pass


class OrganizrAuthError(OrganizrError):
    """Raised when authentication fails (invalid admin credentials)."""

    pass


class OrganizrUserExistsError(OrganizrError):
    """Raised when attempting to create a user that already exists."""

    pass


# =============================================================================
# Organizr API Client
# =============================================================================


class OrganizrClient:
    """
    Async HTTP client for the Organizr v2 REST API.

    Uses session cookie authentication: login once, then the same session
    is used for all requests (aiohttp stores cookies automatically).
    """

    def __init__(self, base_url: str, admin_user: str, admin_password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._session: Optional[aiohttp.ClientSession] = None
        self._logged_in: bool = False

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._logged_in = False

    async def _login(self) -> None:
        """Authenticate with Organizr; session cookie is stored by aiohttp."""
        url = f"{self.base_url}/api/v2/login"
        payload = {
            "username": self.admin_user,
            "password": self.admin_password,
        }
        try:
            async with self.session.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 401:
                    raise OrganizrAuthError("Invalid admin credentials")
                if response.status >= 400:
                    text = await response.text()
                    raise OrganizrError(f"Login failed: {response.status} - {text}")
                data = (
                    await response.json()
                    if response.content_type == "application/json"
                    else {}
                )
                result = data.get("result") if isinstance(data, dict) else None
                if result == "error":
                    raise OrganizrAuthError(
                        data.get("message", "Login failed")
                        if isinstance(data, dict)
                        else "Login failed"
                    )
                self._logged_in = True
                logger.debug("Successfully authenticated with Organizr")
        except aiohttp.ClientConnectorError as e:
            raise OrganizrConnectionError(
                f"Cannot connect to Organizr at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise OrganizrError(f"HTTP error during login: {e}")

    async def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            await self._login()

    async def _request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> dict[str, Any] | list[Any]:
        url = f"{self.base_url}{endpoint}"
        await self._ensure_logged_in()
        headers = kwargs.pop("headers", {})
        if "json" in kwargs and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        try:
            async with self.session.request(
                method, url, headers=headers, **kwargs
            ) as response:
                if response.status == 401:
                    self._logged_in = False
                    await self._login()
                    async with self.session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_response:
                        if retry_response.status == 401:
                            raise OrganizrAuthError("Authentication failed")
                        return await self._handle_response(retry_response)
                return await self._handle_response(response)
        except aiohttp.ClientConnectorError as e:
            raise OrganizrConnectionError(
                f"Cannot connect to Organizr at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise OrganizrError(f"HTTP error: {e}")

    async def _handle_response(
        self, response: aiohttp.ClientResponse
    ) -> dict[str, Any] | list[Any]:
        if response.status >= 400:
            text = await response.text()
            if "already exists" in text.lower() or "duplicate" in text.lower():
                raise OrganizrUserExistsError("User already exists")
            raise OrganizrError(f"API error {response.status}: {text}")
        if response.content_type != "application/json":
            return {}
        data = await response.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def user_exists(self, username: str) -> bool:
        """Check if a user exists (case-insensitive match on username)."""
        try:
            raw = await self._request("GET", "/api/v2/users")
            users = raw if isinstance(raw, list) else []
            for user in users:
                if (
                    isinstance(user, dict)
                    and user.get("username", "").lower() == username.lower()
                ):
                    return True
            return False
        except OrganizrError:
            logger.warning(f"Error checking if user {username} exists")
            raise

    async def create_user(
        self, username: str, password: str, email: str
    ) -> OrganizrUser:
        """Create a new user. Raises OrganizrUserExistsError if user exists."""
        logger.info(f"Creating Organizr user: {username}")
        if await self.user_exists(username):
            raise OrganizrUserExistsError(f"User '{username}' already exists")
        payload = {
            "username": username,
            "password": password,
            "email": email,
        }
        data = await self._request("POST", "/api/v2/users", json=payload)
        user_id = data.get("id", 0) if isinstance(data, dict) else 0
        logger.info(f"Successfully created Organizr user: {username}")
        return OrganizrUser(id=user_id, username=username)


# =============================================================================
# Organizr Service (Multi-URL Failover)
# =============================================================================


class OrganizrService:
    """
    High-level Organizr service with multi-URL failover.

    Tries each URL in order; caches the first working URL for subsequent calls.
    """

    def __init__(self, urls: list[str], admin_user: str, admin_password: str) -> None:
        self.urls = [url.rstrip("/") for url in urls]
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._active_url: str | None = None
        self._client: Optional[OrganizrClient] = None

    @property
    def active_url(self) -> Optional[str]:
        return self._active_url

    async def _ensure_client(self) -> OrganizrClient:
        if self._client is None or self._active_url is None:
            await self.resolve_url()
        assert self._client is not None
        return self._client

    async def resolve_url(self) -> str:
        if not self.urls:
            raise OrganizrError("No Organizr URLs configured")
        errors: list[str] = []
        for url in self.urls:
            logger.debug(f"Trying Organizr URL: {url}")
            client = OrganizrClient(
                base_url=url,
                admin_user=self.admin_user,
                admin_password=self.admin_password,
            )
            try:
                await client._login()
                self._active_url = url
                self._client = client
                return url
            except OrganizrError as e:
                errors.append(f"{url}: {e}")
                await client.close()
        raise OrganizrConnectionError(
            "Could not connect to any Organizr URL: " + "; ".join(errors)
        )

    async def user_exists(self, username: str) -> bool:
        client = await self._ensure_client()
        return await client.user_exists(username)

    async def create_user(
        self, username: str, password: str, email: str
    ) -> OrganizrUser:
        client = await self._ensure_client()
        return await client.create_user(username, password, email)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
        self._active_url = None

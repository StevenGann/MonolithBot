"""
Romm API client and service for MonolithBot.

This module provides an async HTTP client for interacting with the Romm
REST API, as well as a service layer that handles multi-URL failover.

Romm is a ROM management web application. This client handles user
provisioning for the registration feature.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Multi-URL failover support for high availability
    - Structured error hierarchy for different failure modes
    - User provisioning (create, check existence)

Architecture:
    - RommClient: Low-level HTTP client for a single Romm URL
    - RommService: High-level service with multi-URL failover logic

Romm API Endpoints Used:
    - POST /api/token - Authenticate and get token
    - GET /api/users - List users (to check existence)
    - POST /api/users - Create new user

Example:
    >>> from bot.services.romm import RommService
    >>>
    >>> # Create service with multiple URLs for failover
    >>> service = RommService(
    ...     urls=["https://primary.example.com", "https://backup.example.com"],
    ...     admin_user="admin",
    ...     admin_password="password"
    ... )
    >>>
    >>> # Check if user exists
    >>> exists = await service.user_exists("johndoe")
    >>>
    >>> # Create a new user
    >>> await service.create_user("johndoe", "securepassword", "john@example.com")
    >>>
    >>> # Always close when done
    >>> await service.close()

See Also:
    - Romm GitHub: https://github.com/rommapp/romm
    - bot.cogs.registration.handler: Uses this service for user registration
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

# Module logger
logger = logging.getLogger("monolithbot.romm")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RommUser:
    """
    Represents a user in Romm.

    Attributes:
        id: The unique ID for the user.
        username: The username for login.
        enabled: Whether the user account is enabled.
        role: The user's role (e.g., "viewer", "editor", "admin").
    """

    id: int
    username: str
    enabled: bool = True
    role: str = "viewer"


# =============================================================================
# Exceptions
# =============================================================================


class RommError(Exception):
    """
    Base exception for all Romm API errors.

    Catch this to handle any Romm-related failure. For more specific
    handling, catch the subclasses instead.

    Example:
        >>> try:
        ...     await client.create_user("john", "password")
        ... except RommError as e:
        ...     print(f"Romm error: {e}")
    """

    pass


class RommConnectionError(RommError):
    """
    Raised when unable to establish a connection to the Romm server.

    This typically indicates:
        - Server is down or unreachable
        - Network connectivity issues
        - Incorrect URL configuration
        - Firewall blocking the connection

    Example:
        >>> try:
        ...     await client.check_health()
        ... except RommConnectionError:
        ...     print("Server is offline!")
    """

    pass


class RommAuthError(RommError):
    """
    Raised when authentication with Romm fails.

    This indicates:
        - Invalid admin username/password
        - Admin account lacks required permissions
        - Account has been disabled

    Example:
        >>> try:
        ...     await client.create_user("john", "password")
        ... except RommAuthError:
        ...     print("Check your admin credentials")
    """

    pass


class RommUserExistsError(RommError):
    """
    Raised when attempting to create a user that already exists.

    Example:
        >>> try:
        ...     await client.create_user("john", "password")
        ... except RommUserExistsError:
        ...     print("User 'john' already exists")
    """

    pass


# =============================================================================
# Romm API Client
# =============================================================================


class RommClient:
    """
    Async HTTP client for the Romm REST API.

    This client handles all communication with a Romm server, including
    authentication, request/response handling, and error management.

    Romm uses OAuth2-style token-based authentication. The client automatically
    handles login and token management.

    The client uses lazy session initialization - the aiohttp session is only
    created when the first request is made. Always call `close()` when done
    to properly release resources.

    Attributes:
        base_url: The Romm server base URL (without trailing slash).
        admin_user: Admin username for API authentication.
        admin_password: Admin password for API authentication.

    Example:
        >>> async with RommClient(url, admin_user, admin_password) as client:
        ...     await client.create_user("john", "password")

        Or manually managing lifecycle:

        >>> client = RommClient(url, admin_user, admin_password)
        >>> try:
        ...     await client.create_user("john", "password")
        ... finally:
        ...     await client.close()
    """

    def __init__(
        self, base_url: str, admin_user: str, admin_password: str
    ) -> None:
        """
        Initialize the Romm client.

        Args:
            base_url: Romm server URL (e.g., "https://romm.example.com").
                Trailing slashes are automatically stripped.
            admin_user: Admin username for API authentication.
            admin_password: Admin password for API authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """
        Get or create the aiohttp session.

        Uses lazy initialization - the session is created on first access.
        If the session was closed, a new one is created.

        Returns:
            Configured aiohttp ClientSession.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                },
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
        self._token = None

    async def __aenter__(self) -> "RommClient":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

    async def _login(self) -> str:
        """
        Authenticate with Romm and get an access token.

        Romm uses OAuth2 password grant for authentication.

        Returns:
            Access token string.

        Raises:
            RommAuthError: If authentication fails.
            RommConnectionError: If unable to connect.
        """
        url = f"{self.base_url}/api/token"

        # Romm uses form-encoded OAuth2 password grant. The /api/token endpoint
        # requires a scope parameter; without it, the token has no permissions
        # and returns 403 on write operations like POST /api/users.
        # See: https://docs.romm.app/4.5.0/API-and-Development/API-Reference/
        form_data = aiohttp.FormData()
        form_data.add_field("username", self.admin_user)
        form_data.add_field("password", self.admin_password)
        form_data.add_field("scope", "users.read users.write")

        try:
            async with self.session.post(url, data=form_data) as response:
                if response.status == 401:
                    raise RommAuthError("Invalid admin credentials")
                if response.status == 403:
                    raise RommAuthError("Access forbidden")

                if response.status >= 400:
                    text = await response.text()
                    raise RommError(f"Login failed: {response.status} - {text}")

                data = await response.json()
                token = data.get("access_token")

                if not token:
                    raise RommAuthError("No access_token in login response")

                self._token = token
                logger.debug("Successfully authenticated with Romm")
                return token

        except aiohttp.ClientConnectorError as e:
            raise RommConnectionError(
                f"Cannot connect to Romm at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise RommError(f"HTTP error during login: {e}")

    async def _ensure_token(self) -> str:
        """
        Ensure we have a valid authentication token.

        Returns:
            Access token string.
        """
        if self._token is None:
            await self._login()
        return self._token

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """
        Make an authenticated HTTP request to the Romm API.

        This is the core request method used by all public API methods.
        It handles authentication, error responses, and connection failures.

        Args:
            method: HTTP method ("GET", "POST", etc.).
            endpoint: API endpoint path (e.g., "/api/users").
                Should start with a forward slash.
            **kwargs: Additional arguments passed to aiohttp's request method.
                Common: params (dict), json (dict), timeout (float).

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            RommConnectionError: If unable to connect to the server.
            RommAuthError: If authentication fails (401/403 response).
            RommError: For other HTTP errors (4xx/5xx responses).
        """
        url = f"{self.base_url}{endpoint}"
        token = await self._ensure_token()

        # Add Authorization header
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        try:
            async with self.session.request(
                method, url, headers=headers, **kwargs
            ) as response:
                # Handle authentication errors - may need to re-login
                if response.status == 401:
                    # Token may have expired, try re-login once
                    self._token = None
                    token = await self._ensure_token()
                    headers["Authorization"] = f"Bearer {token}"

                    # Retry the request
                    async with self.session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_response:
                        if retry_response.status == 401:
                            raise RommAuthError("Authentication failed")
                        return await self._handle_response(retry_response)

                return await self._handle_response(response)

        except aiohttp.ClientConnectorError as e:
            raise RommConnectionError(
                f"Cannot connect to Romm at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise RommError(f"HTTP error: {e}")

    async def _handle_response(
        self, response: aiohttp.ClientResponse
    ) -> dict[str, Any] | list[Any]:
        """
        Handle HTTP response and extract JSON data.

        Args:
            response: The aiohttp response object.

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            RommAuthError: If authentication fails.
            RommUserExistsError: If user already exists (on create).
            RommError: For other errors.
        """
        if response.status == 403:
            raise RommAuthError("Access forbidden - check admin permissions")

        # Handle other HTTP errors
        if response.status >= 400:
            text = await response.text()

            # Check for user exists error
            if "already exists" in text.lower() or "duplicate" in text.lower():
                raise RommUserExistsError("User already exists")

            raise RommError(f"API error {response.status}: {text}")

        # Parse JSON response
        if response.content_type == "application/json":
            return await response.json()

        # For non-JSON responses, return empty dict
        return {}

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------

    async def check_health(self) -> bool:
        """
        Check if the Romm server is healthy and responding.

        Attempts to authenticate with the server to verify it is online
        and accepting requests.

        Returns:
            True if the server is healthy.

        Raises:
            RommConnectionError: If unable to connect.
            RommAuthError: If authentication fails.
            RommError: For other errors.

        Example:
            >>> healthy = await client.check_health()
            >>> if healthy:
            ...     print("Romm is online")
        """
        # Try to login to verify server is up and credentials work
        await self._login()
        return True

    async def user_exists(self, username: str) -> bool:
        """
        Check if a user exists in Romm.

        Args:
            username: The username to check.

        Returns:
            True if the user exists, False otherwise.

        Example:
            >>> if await client.user_exists("john"):
            ...     print("User john exists")
        """
        try:
            # Get list of users and check if username exists
            data = await self._request("GET", "/api/users")

            # Romm returns a list of users
            users = data if isinstance(data, list) else []

            for user in users:
                if user.get("username", "").lower() == username.lower():
                    return True

            return False

        except RommError:
            logger.warning(f"Error checking if user {username} exists")
            raise

    async def create_user(
        self,
        username: str,
        password: str,
        email: str,
        role: str = "viewer",
    ) -> RommUser:
        """
        Create a new user in Romm.

        Args:
            username: The username for the new user. Must be unique.
            password: The password for the new user.
            email: The email address for the new user. Required by Romm API.
            role: The user's role. Options: "viewer", "editor", "admin".
                Defaults to "viewer".

        Returns:
            RommUser object representing the created user.

        Raises:
            RommUserExistsError: If the user already exists.
            RommAuthError: If admin credentials are invalid.
            RommConnectionError: If unable to connect.
            RommError: For other errors.

        Example:
            >>> user = await client.create_user(
            ...     "johndoe",
            ...     "securepassword123",
            ...     "john@example.com"
            ... )
            >>> print(f"Created user: {user.username}")
        """
        logger.info(f"Creating Romm user: {username}")

        # Check if user already exists
        if await self.user_exists(username):
            raise RommUserExistsError(f"User '{username}' already exists")

        # Build user data (Romm API requires email)
        user_data = {
            "username": username,
            "password": password,
            "email": email,
            "role": role,
        }

        data = await self._request("POST", "/api/users", json=user_data)

        # Handle response - could be dict or list
        if isinstance(data, dict):
            user_id = data.get("id", 0)
        else:
            user_id = 0

        logger.info(f"Successfully created Romm user: {username}")

        return RommUser(
            id=user_id,
            username=username,
            enabled=True,
            role=role,
        )

    async def get_users(self) -> list[RommUser]:
        """
        Get list of all users.

        Returns:
            List of RommUser objects.

        Example:
            >>> users = await client.get_users()
            >>> for user in users:
            ...     print(f"{user.username}: {user.role}")
        """
        data = await self._request("GET", "/api/users")

        users = data if isinstance(data, list) else []

        return [
            RommUser(
                id=user.get("id", 0),
                username=user.get("username", ""),
                enabled=user.get("enabled", True),
                role=user.get("role", "viewer"),
            )
            for user in users
        ]

    async def get_user_id(self, username: str) -> Optional[int]:
        """
        Get the user ID for a given username.

        Args:
            username: The username to look up (case-insensitive).

        Returns:
            The user's ID if found, None otherwise.

        Example:
            >>> user_id = await client.get_user_id("john")
            >>> if user_id:
            ...     print(f"User ID: {user_id}")
        """
        try:
            data = await self._request("GET", "/api/users")
            users = data if isinstance(data, list) else []

            username_lower = username.lower()
            for user in users:
                if user.get("username", "").lower() == username_lower:
                    return user.get("id")

            return None
        except RommError:
            return None

    async def set_password(self, username: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Args:
            username: The username of the user to update.
            new_password: The new password to set.

        Returns:
            True if the password was successfully set.

        Raises:
            RommError: If the user doesn't exist or update fails.
            RommAuthError: If admin credentials are invalid.
            RommConnectionError: If unable to connect.

        Example:
            >>> await client.set_password("john", "newSecurePassword123")
        """
        logger.info(f"Setting password for Romm user: {username}")

        # Get the user ID
        user_id = await self.get_user_id(username)
        if not user_id:
            raise RommError(f"User '{username}' not found")

        # Romm API: PUT /api/users/{id} with JSON body
        await self._request(
            "PUT",
            f"/api/users/{user_id}",
            json={
                "password": new_password,
            },
        )

        logger.info(f"Successfully set password for Romm user: {username}")
        return True


# =============================================================================
# Romm Service (Multi-URL Failover)
# =============================================================================


class RommService:
    """
    High-level Romm service with multi-URL failover support.

    This service wraps RommClient and provides automatic failover
    between multiple Romm server URLs. URLs are tried in order during
    health checks, and the working URL is cached for subsequent API calls.

    Key behaviors:
        - Health checks always start from the top of the URL list, preferring
          the primary server when it recovers from an outage.
        - Other API calls use the cached active URL for efficiency.
        - If no URL has been resolved yet, API calls trigger URL resolution.

    Attributes:
        urls: List of Romm server URLs to try, in priority order.
        admin_user: Admin username for authentication.
        admin_password: Admin password for authentication.
        active_url: The currently active (working) URL, or None if not yet resolved.

    Example:
        >>> service = RommService(
        ...     urls=["https://primary.example.com", "https://backup.example.com"],
        ...     admin_user="admin",
        ...     admin_password="password"
        ... )
        >>>
        >>> # Health check tries URLs in order
        >>> await service.check_health()
        >>> print(f"Connected via {service.active_url}")
        >>>
        >>> # Create a user
        >>> user = await service.create_user("john", "password", "john@example.com")
        >>>
        >>> await service.close()

    See Also:
        - RommClient: Low-level single-URL client used internally.
        - bot.config.RommConfig: Configuration with URL list.
    """

    def __init__(
        self, urls: list[str], admin_user: str, admin_password: str
    ) -> None:
        """
        Initialize the Romm service.

        Args:
            urls: List of Romm server URLs to try, in priority order.
                The first URL is considered the "primary" and is preferred
                when available. Each URL should be a base URL like
                "https://romm.example.com" (trailing slashes are stripped).
            admin_user: Admin username for API authentication.
            admin_password: Admin password for API authentication.
        """
        self.urls = [url.rstrip("/") for url in urls]
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._active_url: str | None = None
        self._client: RommClient | None = None

    @property
    def active_url(self) -> str | None:
        """
        Get the currently active (working) URL.

        Returns:
            The URL that successfully passed the last health check,
            or None if no URL has been resolved yet.
        """
        return self._active_url

    async def _ensure_client(self) -> RommClient:
        """
        Ensure we have a working client, resolving URL if needed.

        If no active URL is set, triggers URL resolution by trying
        each URL in order until one responds successfully.

        Returns:
            A RommClient connected to the active URL.

        Raises:
            RommError: If no URLs are configured or all URLs fail.
        """
        if self._client is None or self._active_url is None:
            await self.resolve_url()
        return self._client

    async def resolve_url(self) -> str:
        """
        Try URLs in order and return the first working one.

        This method attempts to connect to each URL in the configured
        list, stopping at the first one that responds successfully.
        The working URL and its client are cached for subsequent calls.

        This is called automatically by health checks and is also
        triggered by API calls if no URL has been resolved yet.

        Returns:
            The URL that successfully responded.

        Raises:
            RommConnectionError: If all URLs fail to connect.
            RommError: If no URLs are configured.

        Example:
            >>> url = await service.resolve_url()
            >>> print(f"Using {url}")
        """
        if not self.urls:
            raise RommError("No Romm URLs configured")

        errors: list[str] = []

        for url in self.urls:
            logger.debug(f"Trying Romm URL: {url}")
            client = RommClient(
                base_url=url,
                admin_user=self.admin_user,
                admin_password=self.admin_password,
            )

            try:
                await client.check_health()
                # Success! Update cached client and URL
                if self._client and self._client is not client:
                    await self._client.close()
                self._client = client
                self._active_url = url
                logger.info(f"Romm URL resolved: {url}")
                return url

            except RommConnectionError as e:
                logger.warning(f"Failed to connect to {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

            except RommError as e:
                logger.warning(f"Romm error at {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

        # All URLs failed
        error_summary = "; ".join(errors)
        raise RommConnectionError(f"All Romm URLs failed: {error_summary}")

    async def check_health(self) -> bool:
        """
        Check Romm server health, starting from the primary URL.

        Unlike other API methods that use the cached active URL, health
        checks always start from the top of the URL list. This ensures
        that when the primary server recovers from an outage, subsequent
        health checks will detect this and switch back to it.

        Returns:
            True if the server is healthy.

        Raises:
            RommConnectionError: If all URLs fail to connect.
            RommAuthError: If authentication fails on all URLs.
            RommError: If all URLs return errors.

        Example:
            >>> await service.check_health()
            >>> print(f"Healthy, using {service.active_url}")
        """
        # Always try from the top of the URL list for health checks
        await self.resolve_url()

        # Now get the actual health status from the resolved client
        return await self._client.check_health()

    # -------------------------------------------------------------------------
    # Delegated API Methods
    # -------------------------------------------------------------------------

    async def user_exists(self, username: str) -> bool:
        """
        Check if a user exists in Romm.

        Delegates to the underlying RommClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See RommClient.user_exists for full documentation.
        """
        client = await self._ensure_client()
        return await client.user_exists(username)

    async def create_user(
        self,
        username: str,
        password: str,
        email: str,
        role: str = "viewer",
    ) -> RommUser:
        """
        Create a new user in Romm.

        Delegates to the underlying RommClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See RommClient.create_user for full documentation.
        """
        client = await self._ensure_client()
        return await client.create_user(
            username=username,
            password=password,
            email=email,
            role=role,
        )

    async def get_users(self) -> list[RommUser]:
        """
        Get list of all users.

        Delegates to the underlying RommClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See RommClient.get_users for full documentation.
        """
        client = await self._ensure_client()
        return await client.get_users()

    async def get_user_id(self, username: str) -> Optional[int]:
        """
        Get the user ID for a given username.

        Delegates to the underlying RommClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See RommClient.get_user_id for full documentation.
        """
        client = await self._ensure_client()
        return await client.get_user_id(username)

    async def set_password(self, username: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Delegates to the underlying RommClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See RommClient.set_password for full documentation.
        """
        client = await self._ensure_client()
        return await client.set_password(username, new_password)

    async def close(self) -> None:
        """
        Close the service and release resources.

        Closes the underlying RommClient's HTTP session. Safe to call
        multiple times or if no client was ever created.
        """
        if self._client:
            await self._client.close()
            self._client = None
        self._active_url = None

    async def __aenter__(self) -> "RommService":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

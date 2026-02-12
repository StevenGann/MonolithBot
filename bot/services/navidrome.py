"""
Navidrome API client and service for MonolithBot.

This module provides an async HTTP client for interacting with the Navidrome
REST API, as well as a service layer that handles multi-URL failover.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Multi-URL failover support for high availability
    - Structured error hierarchy for different failure modes
    - User provisioning (create, check existence)

Architecture:
    - NavidromeClient: Low-level HTTP client for a single Navidrome URL
    - NavidromeService: High-level service with multi-URL failover logic

Navidrome API Endpoints Used:
    - POST /auth/login - Authenticate and get token
    - GET /api/user - List users (to check existence)
    - POST /api/user - Create new user

Example:
    >>> from bot.services.navidrome import NavidromeService
    >>>
    >>> # Create service with multiple URLs for failover
    >>> service = NavidromeService(
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
    - Navidrome GitHub: https://github.com/navidrome/navidrome
    - bot.cogs.registration.handler: Uses this service for user registration
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

# Module logger
logger = logging.getLogger("monolithbot.navidrome")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NavidromeUser:
    """
    Represents a user in Navidrome.

    Attributes:
        id: The unique ID for the user (UUID format).
        user_name: The username for login.
        email: The user's email address.
        is_admin: Whether the user has admin privileges.
    """

    id: str
    user_name: str
    email: Optional[str] = None
    is_admin: bool = False


# =============================================================================
# Exceptions
# =============================================================================


class NavidromeError(Exception):
    """
    Base exception for all Navidrome API errors.

    Catch this to handle any Navidrome-related failure. For more specific
    handling, catch the subclasses instead.

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NavidromeError as e:
        ...     print(f"Navidrome error: {e}")
    """

    pass


class NavidromeConnectionError(NavidromeError):
    """
    Raised when unable to establish a connection to the Navidrome server.

    This typically indicates:
        - Server is down or unreachable
        - Network connectivity issues
        - Incorrect URL configuration
        - Firewall blocking the connection

    Example:
        >>> try:
        ...     await client.check_health()
        ... except NavidromeConnectionError:
        ...     print("Server is offline!")
    """

    pass


class NavidromeAuthError(NavidromeError):
    """
    Raised when authentication with Navidrome fails.

    This indicates:
        - Invalid admin username/password
        - Admin account lacks required permissions
        - Account has been disabled

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NavidromeAuthError:
        ...     print("Check your admin credentials")
    """

    pass


class NavidromeUserExistsError(NavidromeError):
    """
    Raised when attempting to create a user that already exists.

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NavidromeUserExistsError:
        ...     print("User 'john' already exists")
    """

    pass


# =============================================================================
# Navidrome API Client
# =============================================================================


class NavidromeClient:
    """
    Async HTTP client for the Navidrome REST API.

    This client handles all communication with a Navidrome server, including
    authentication, request/response handling, and error management.

    Navidrome uses JWT token-based authentication. The client automatically
    handles login and token management.

    The client uses lazy session initialization - the aiohttp session is only
    created when the first request is made. Always call `close()` when done
    to properly release resources.

    Attributes:
        base_url: The Navidrome server base URL (without trailing slash).
        admin_user: Admin username for API authentication.
        admin_password: Admin password for API authentication.

    Example:
        >>> async with NavidromeClient(url, admin_user, admin_password) as client:
        ...     await client.create_user("john", "password", "john@example.com")

        Or manually managing lifecycle:

        >>> client = NavidromeClient(url, admin_user, admin_password)
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... finally:
        ...     await client.close()
    """

    def __init__(self, base_url: str, admin_user: str, admin_password: str) -> None:
        """
        Initialize the Navidrome client.

        Args:
            base_url: Navidrome server URL (e.g., "https://navidrome.example.com").
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
                    "Content-Type": "application/json",
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

    async def __aenter__(self) -> "NavidromeClient":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

    async def _login(self) -> str:
        """
        Authenticate with Navidrome and get a JWT token.

        Returns:
            JWT token string.

        Raises:
            NavidromeAuthError: If authentication fails.
            NavidromeConnectionError: If unable to connect.
        """
        url = f"{self.base_url}/auth/login"

        try:
            async with self.session.post(
                url,
                json={
                    "username": self.admin_user,
                    "password": self.admin_password,
                },
            ) as response:
                if response.status == 401:
                    raise NavidromeAuthError("Invalid admin credentials")
                if response.status == 403:
                    raise NavidromeAuthError("Access forbidden")

                if response.status >= 400:
                    text = await response.text()
                    raise NavidromeError(f"Login failed: {response.status} - {text}")

                data = await response.json()
                token = data.get("token")

                if not token:
                    raise NavidromeAuthError("No token in login response")

                self._token = token
                logger.debug("Successfully authenticated with Navidrome")
                return token

        except aiohttp.ClientConnectorError as e:
            raise NavidromeConnectionError(
                f"Cannot connect to Navidrome at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise NavidromeError(f"HTTP error during login: {e}")

    async def _ensure_token(self) -> str:
        """
        Ensure we have a valid authentication token.

        Returns:
            JWT token string.
        """
        if self._token is None:
            await self._login()
        return self._token

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an authenticated HTTP request to the Navidrome API.

        This is the core request method used by all public API methods.
        It handles authentication, error responses, and connection failures.

        Args:
            method: HTTP method ("GET", "POST", etc.).
            endpoint: API endpoint path (e.g., "/api/user").
                Should start with a forward slash.
            **kwargs: Additional arguments passed to aiohttp's request method.
                Common: params (dict), json (dict), timeout (float).

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            NavidromeConnectionError: If unable to connect to the server.
            NavidromeAuthError: If authentication fails (401/403 response).
            NavidromeError: For other HTTP errors (4xx/5xx responses).
        """
        url = f"{self.base_url}{endpoint}"
        token = await self._ensure_token()

        # Add Authorization header
        headers = kwargs.pop("headers", {})
        headers["x-nd-authorization"] = f"Bearer {token}"

        try:
            async with self.session.request(
                method, url, headers=headers, **kwargs
            ) as response:
                # Handle authentication errors - may need to re-login
                if response.status == 401:
                    # Token may have expired, try re-login once
                    self._token = None
                    token = await self._ensure_token()
                    headers["x-nd-authorization"] = f"Bearer {token}"

                    # Retry the request
                    async with self.session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_response:
                        if retry_response.status == 401:
                            raise NavidromeAuthError("Authentication failed")
                        return await self._handle_response(retry_response)

                return await self._handle_response(response)

        except aiohttp.ClientConnectorError as e:
            raise NavidromeConnectionError(
                f"Cannot connect to Navidrome at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise NavidromeError(f"HTTP error: {e}")

    async def _handle_response(
        self, response: aiohttp.ClientResponse
    ) -> dict[str, Any]:
        """
        Handle HTTP response and extract JSON data.

        Args:
            response: The aiohttp response object.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            NavidromeAuthError: If authentication fails.
            NavidromeUserExistsError: If user already exists (on create).
            NavidromeError: For other errors.
        """
        if response.status == 403:
            raise NavidromeAuthError("Access forbidden - check admin permissions")

        # Handle other HTTP errors
        if response.status >= 400:
            text = await response.text()

            # Check for user exists error
            if response.status == 422 and "already exists" in text.lower():
                raise NavidromeUserExistsError("User already exists")

            raise NavidromeError(f"API error {response.status}: {text}")

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
        Check if the Navidrome server is healthy and responding.

        Attempts to authenticate with the server to verify it is online
        and accepting requests.

        Returns:
            True if the server is healthy.

        Raises:
            NavidromeConnectionError: If unable to connect.
            NavidromeAuthError: If authentication fails.
            NavidromeError: For other errors.

        Example:
            >>> healthy = await client.check_health()
            >>> if healthy:
            ...     print("Navidrome is online")
        """
        # Try to login to verify server is up and credentials work
        await self._login()
        return True

    async def user_exists(self, user_name: str) -> bool:
        """
        Check if a user exists in Navidrome.

        Args:
            user_name: The username to check.

        Returns:
            True if the user exists, False otherwise.

        Example:
            >>> if await client.user_exists("john"):
            ...     print("User john exists")
        """
        try:
            # Get list of users and check if username exists
            data = await self._request("GET", "/api/user")

            # Navidrome returns a list of users
            users = data if isinstance(data, list) else []

            for user in users:
                if user.get("userName", "").lower() == user_name.lower():
                    return True

            return False

        except NavidromeError:
            # On error, assume user might exist to be safe
            logger.warning(f"Error checking if user {user_name} exists")
            raise

    async def create_user(
        self,
        user_name: str,
        password: str,
        email: Optional[str] = None,
        is_admin: bool = False,
    ) -> NavidromeUser:
        """
        Create a new user in Navidrome.

        Args:
            user_name: The username for the new user. Must be unique.
            password: The password for the new user.
            email: Optional email address for the user.
            is_admin: Whether the user should have admin privileges.
                Defaults to False.

        Returns:
            NavidromeUser object representing the created user.

        Raises:
            NavidromeUserExistsError: If the user already exists.
            NavidromeAuthError: If admin credentials are invalid.
            NavidromeConnectionError: If unable to connect.
            NavidromeError: For other errors.

        Example:
            >>> user = await client.create_user(
            ...     "johndoe",
            ...     "securepassword123",
            ...     email="john@example.com"
            ... )
            >>> print(f"Created user: {user.user_name}")
        """
        logger.info(f"Creating Navidrome user: {user_name}")

        # Check if user already exists
        if await self.user_exists(user_name):
            raise NavidromeUserExistsError(f"User '{user_name}' already exists")

        # Build user data
        user_data = {
            "userName": user_name,
            "password": password,
            "isAdmin": is_admin,
        }

        if email:
            user_data["email"] = email

        data = await self._request("POST", "/api/user", json=user_data)

        logger.info(f"Successfully created Navidrome user: {user_name}")

        return NavidromeUser(
            id=data.get("id", ""),
            user_name=user_name,
            email=email,
            is_admin=is_admin,
        )

    async def get_users(self) -> list[NavidromeUser]:
        """
        Get list of all users.

        Returns:
            List of NavidromeUser objects.

        Example:
            >>> users = await client.get_users()
            >>> for user in users:
            ...     print(f"{user.user_name}: {user.email}")
        """
        data = await self._request("GET", "/api/user")

        users = data if isinstance(data, list) else []

        return [
            NavidromeUser(
                id=user.get("id", ""),
                user_name=user.get("userName", ""),
                email=user.get("email"),
                is_admin=user.get("isAdmin", False),
            )
            for user in users
        ]

    async def get_user_id(self, user_name: str) -> Optional[str]:
        """
        Get the user ID for a given username.

        Args:
            user_name: The username to look up (case-insensitive).

        Returns:
            The user's ID if found, None otherwise.

        Example:
            >>> user_id = await client.get_user_id("john")
            >>> if user_id:
            ...     print(f"User ID: {user_id}")
        """
        try:
            data = await self._request("GET", "/api/user")
            users = data if isinstance(data, list) else []

            user_name_lower = user_name.lower()
            for user in users:
                if user.get("userName", "").lower() == user_name_lower:
                    return user.get("id")

            return None
        except NavidromeError:
            return None

    async def set_password(self, user_name: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Args:
            user_name: The username of the user to update.
            new_password: The new password to set.

        Returns:
            True if the password was successfully set.

        Raises:
            NavidromeError: If the user doesn't exist or update fails.
            NavidromeAuthError: If admin credentials are invalid.
            NavidromeConnectionError: If unable to connect.

        Example:
            >>> await client.set_password("john", "newSecurePassword123")
        """
        logger.info(f"Setting password for Navidrome user: {user_name}")

        # Get the user ID
        user_id = await self.get_user_id(user_name)
        if not user_id:
            raise NavidromeError(f"User '{user_name}' not found")

        # Navidrome API: PUT /api/user/{id} with JSON body
        await self._request(
            "PUT",
            f"/api/user/{user_id}",
            json={
                "password": new_password,
            },
        )

        logger.info(f"Successfully set password for Navidrome user: {user_name}")
        return True


# =============================================================================
# Navidrome Service (Multi-URL Failover)
# =============================================================================


class NavidromeService:
    """
    High-level Navidrome service with multi-URL failover support.

    This service wraps NavidromeClient and provides automatic failover
    between multiple Navidrome server URLs. URLs are tried in order during
    health checks, and the working URL is cached for subsequent API calls.

    Key behaviors:
        - Health checks always start from the top of the URL list, preferring
          the primary server when it recovers from an outage.
        - Other API calls use the cached active URL for efficiency.
        - If no URL has been resolved yet, API calls trigger URL resolution.

    Attributes:
        urls: List of Navidrome server URLs to try, in priority order.
        admin_user: Admin username for authentication.
        admin_password: Admin password for authentication.
        active_url: The currently active (working) URL, or None if not yet resolved.

    Example:
        >>> service = NavidromeService(
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
        - NavidromeClient: Low-level single-URL client used internally.
        - bot.config.NavidromeConfig: Configuration with URL list.
    """

    def __init__(self, urls: list[str], admin_user: str, admin_password: str) -> None:
        """
        Initialize the Navidrome service.

        Args:
            urls: List of Navidrome server URLs to try, in priority order.
                The first URL is considered the "primary" and is preferred
                when available. Each URL should be a base URL like
                "https://navidrome.example.com" (trailing slashes are stripped).
            admin_user: Admin username for API authentication.
            admin_password: Admin password for API authentication.
        """
        self.urls = [url.rstrip("/") for url in urls]
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._active_url: str | None = None
        self._client: NavidromeClient | None = None

    @property
    def active_url(self) -> str | None:
        """
        Get the currently active (working) URL.

        Returns:
            The URL that successfully passed the last health check,
            or None if no URL has been resolved yet.
        """
        return self._active_url

    async def _ensure_client(self) -> NavidromeClient:
        """
        Ensure we have a working client, resolving URL if needed.

        If no active URL is set, triggers URL resolution by trying
        each URL in order until one responds successfully.

        Returns:
            A NavidromeClient connected to the active URL.

        Raises:
            NavidromeError: If no URLs are configured or all URLs fail.
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
            NavidromeConnectionError: If all URLs fail to connect.
            NavidromeError: If no URLs are configured.

        Example:
            >>> url = await service.resolve_url()
            >>> print(f"Using {url}")
        """
        if not self.urls:
            raise NavidromeError("No Navidrome URLs configured")

        errors: list[str] = []

        for url in self.urls:
            logger.debug(f"Trying Navidrome URL: {url}")
            client = NavidromeClient(
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
                logger.info(f"Navidrome URL resolved: {url}")
                return url

            except NavidromeConnectionError as e:
                logger.warning(f"Failed to connect to {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

            except NavidromeError as e:
                logger.warning(f"Navidrome error at {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

        # All URLs failed
        error_summary = "; ".join(errors)
        raise NavidromeConnectionError(f"All Navidrome URLs failed: {error_summary}")

    async def check_health(self) -> bool:
        """
        Check Navidrome server health, starting from the primary URL.

        Unlike other API methods that use the cached active URL, health
        checks always start from the top of the URL list. This ensures
        that when the primary server recovers from an outage, subsequent
        health checks will detect this and switch back to it.

        Returns:
            True if the server is healthy.

        Raises:
            NavidromeConnectionError: If all URLs fail to connect.
            NavidromeAuthError: If authentication fails on all URLs.
            NavidromeError: If all URLs return errors.

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

    async def user_exists(self, user_name: str) -> bool:
        """
        Check if a user exists in Navidrome.

        Delegates to the underlying NavidromeClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NavidromeClient.user_exists for full documentation.
        """
        client = await self._ensure_client()
        return await client.user_exists(user_name)

    async def create_user(
        self,
        user_name: str,
        password: str,
        email: Optional[str] = None,
        is_admin: bool = False,
    ) -> NavidromeUser:
        """
        Create a new user in Navidrome.

        Delegates to the underlying NavidromeClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NavidromeClient.create_user for full documentation.
        """
        client = await self._ensure_client()
        return await client.create_user(
            user_name=user_name,
            password=password,
            email=email,
            is_admin=is_admin,
        )

    async def get_users(self) -> list[NavidromeUser]:
        """
        Get list of all users.

        Delegates to the underlying NavidromeClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NavidromeClient.get_users for full documentation.
        """
        client = await self._ensure_client()
        return await client.get_users()

    async def get_user_id(self, user_name: str) -> Optional[str]:
        """
        Get the user ID for a given username.

        Delegates to the underlying NavidromeClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NavidromeClient.get_user_id for full documentation.
        """
        client = await self._ensure_client()
        return await client.get_user_id(user_name)

    async def set_password(self, user_name: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Delegates to the underlying NavidromeClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NavidromeClient.set_password for full documentation.
        """
        client = await self._ensure_client()
        return await client.set_password(user_name, new_password)

    async def close(self) -> None:
        """
        Close the service and release resources.

        Closes the underlying NavidromeClient's HTTP session. Safe to call
        multiple times or if no client was ever created.
        """
        if self._client:
            await self._client.close()
            self._client = None
        self._active_url = None

    async def __aenter__(self) -> "NavidromeService":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

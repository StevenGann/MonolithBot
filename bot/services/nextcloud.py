"""
NextCloud API client and service for MonolithBot.

This module provides an async HTTP client for interacting with the NextCloud
OCS Provisioning API, as well as a service layer that handles multi-URL failover.

Key Features:
    - Async/await support using aiohttp
    - Automatic session management with lazy initialization
    - Multi-URL failover support for high availability
    - Structured error hierarchy for different failure modes
    - User provisioning (create, check existence)

Architecture:
    - NextCloudClient: Low-level HTTP client for a single NextCloud URL
    - NextCloudService: High-level service with multi-URL failover logic

NextCloud OCS API Endpoints Used:
    - GET /ocs/v1.php/cloud/users/{userid} - Check if user exists
    - POST /ocs/v1.php/cloud/users - Create new user

Example:
    >>> from bot.services.nextcloud import NextCloudService
    >>>
    >>> # Create service with multiple URLs for failover
    >>> service = NextCloudService(
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
    - NextCloud OCS API: https://docs.nextcloud.com/server/latest/admin_manual/
    - bot.cogs.registration.handler: Uses this service for user registration
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

# Module logger
logger = logging.getLogger("monolithbot.nextcloud")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NextCloudUser:
    """
    Represents a user in NextCloud.

    Attributes:
        user_id: The unique username/ID for the user.
        email: The user's email address.
        display_name: The user's display name (may differ from user_id).
    """

    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None


# =============================================================================
# Exceptions
# =============================================================================


class NextCloudError(Exception):
    """
    Base exception for all NextCloud API errors.

    Catch this to handle any NextCloud-related failure. For more specific
    handling, catch the subclasses instead.

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NextCloudError as e:
        ...     print(f"NextCloud error: {e}")
    """

    pass


class NextCloudConnectionError(NextCloudError):
    """
    Raised when unable to establish a connection to the NextCloud server.

    This typically indicates:
        - Server is down or unreachable
        - Network connectivity issues
        - Incorrect URL configuration
        - Firewall blocking the connection

    Example:
        >>> try:
        ...     await client.check_health()
        ... except NextCloudConnectionError:
        ...     print("Server is offline!")
    """

    pass


class NextCloudAuthError(NextCloudError):
    """
    Raised when authentication with NextCloud fails.

    This indicates:
        - Invalid admin username/password
        - Admin account lacks required permissions
        - Account has been disabled

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NextCloudAuthError:
        ...     print("Check your admin credentials")
    """

    pass


class NextCloudUserExistsError(NextCloudError):
    """
    Raised when attempting to create a user that already exists.

    Example:
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... except NextCloudUserExistsError:
        ...     print("User 'john' already exists")
    """

    pass


# =============================================================================
# NextCloud API Client
# =============================================================================


class NextCloudClient:
    """
    Async HTTP client for the NextCloud OCS Provisioning API.

    This client handles all communication with a NextCloud server, including
    authentication, request/response handling, and error management.

    The client uses lazy session initialization - the aiohttp session is only
    created when the first request is made. Always call `close()` when done
    to properly release resources.

    Attributes:
        base_url: The NextCloud server base URL (without trailing slash).
        admin_user: Admin username for OCS API authentication.
        admin_password: Admin password for OCS API authentication.

    Example:
        >>> async with NextCloudClient(url, admin_user, admin_password) as client:
        ...     await client.create_user("john", "password", "john@example.com")

        Or manually managing lifecycle:

        >>> client = NextCloudClient(url, admin_user, admin_password)
        >>> try:
        ...     await client.create_user("john", "password", "john@example.com")
        ... finally:
        ...     await client.close()
    """

    def __init__(self, base_url: str, admin_user: str, admin_password: str) -> None:
        """
        Initialize the NextCloud client.

        Args:
            base_url: NextCloud server URL (e.g., "https://nextcloud.example.com").
                Trailing slashes are automatically stripped.
            admin_user: Admin username for OCS API authentication.
            admin_password: Admin password for OCS API authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
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
            # NextCloud OCS API uses Basic Auth
            auth = aiohttp.BasicAuth(self.admin_user, self.admin_password)
            self._session = aiohttp.ClientSession(
                auth=auth,
                headers={
                    # Required header for OCS API
                    "OCS-APIRequest": "true",
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

    async def __aenter__(self) -> "NextCloudClient":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the NextCloud OCS API.

        This is the core request method used by all public API methods.
        It handles authentication, error responses, and connection failures.

        Args:
            method: HTTP method ("GET", "POST", etc.).
            endpoint: API endpoint path (e.g., "/ocs/v1.php/cloud/users").
                Should start with a forward slash.
            **kwargs: Additional arguments passed to aiohttp's request method.
                Common: params (dict), data (dict), timeout (float).

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            NextCloudConnectionError: If unable to connect to the server.
            NextCloudAuthError: If authentication fails (401/403 response).
            NextCloudError: For other HTTP errors (4xx/5xx responses).
        """
        url = f"{self.base_url}{endpoint}"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                # Handle authentication errors
                if response.status == 401:
                    raise NextCloudAuthError("Invalid admin credentials")
                if response.status == 403:
                    raise NextCloudAuthError(
                        "Access forbidden - check admin permissions"
                    )

                # Parse JSON response
                if response.content_type == "application/json":
                    data = await response.json()
                else:
                    # Try to parse as JSON anyway (OCS API sometimes returns
                    # wrong content-type)
                    try:
                        data = await response.json()
                    except Exception:
                        text = await response.text()
                        raise NextCloudError(
                            f"Unexpected response format: {text[:200]}"
                        )

                # Check OCS status code in response
                ocs = data.get("ocs", {})
                meta = ocs.get("meta", {})
                status_code = meta.get("statuscode", 0)

                # OCS status codes:
                # 100 = success
                # 101 = invalid input data
                # 102 = user already exists
                # 103 = unknown error
                # 997 = unauthorized
                if status_code == 997:
                    raise NextCloudAuthError("OCS API authentication failed")
                if status_code == 102:
                    raise NextCloudUserExistsError(
                        meta.get("message", "User already exists")
                    )
                if status_code not in (100, 200):
                    message = meta.get("message", f"OCS error {status_code}")
                    raise NextCloudError(f"OCS API error: {message}")

                return data

        except aiohttp.ClientConnectorError as e:
            raise NextCloudConnectionError(
                f"Cannot connect to NextCloud at {self.base_url}: {e}"
            )
        except aiohttp.ClientError as e:
            raise NextCloudError(f"HTTP error: {e}")

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------

    async def check_health(self) -> bool:
        """
        Check if the NextCloud server is healthy and responding.

        Makes a request to the OCS capabilities endpoint to verify the server
        is online and accepting authenticated requests.

        Returns:
            True if the server is healthy.

        Raises:
            NextCloudConnectionError: If unable to connect.
            NextCloudAuthError: If authentication fails.
            NextCloudError: For other errors.

        Example:
            >>> healthy = await client.check_health()
            >>> if healthy:
            ...     print("NextCloud is online")
        """
        # Use capabilities endpoint as health check
        await self._request("GET", "/ocs/v1.php/cloud/capabilities")
        return True

    async def user_exists(self, user_id: str) -> bool:
        """
        Check if a user exists in NextCloud.

        Args:
            user_id: The username to check.

        Returns:
            True if the user exists, False otherwise.

        Example:
            >>> if await client.user_exists("john"):
            ...     print("User john exists")
        """
        try:
            await self._request("GET", f"/ocs/v1.php/cloud/users/{user_id}")
            return True
        except NextCloudError as e:
            msg = str(e).lower()
            # OCS returns "User does not exist" or "not found" for non-existent users
            if (
                "not found" in msg
                or "404" in msg
                or "user does not exist" in msg
                or "does not exist" in msg
            ):
                return False
            raise

    async def create_user(
        self,
        user_id: str,
        password: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> NextCloudUser:
        """
        Create a new user in NextCloud.

        Args:
            user_id: The username for the new user. Must be unique.
            password: The password for the new user.
            email: Optional email address for the user.
            display_name: Optional display name. Defaults to user_id if not provided.

        Returns:
            NextCloudUser object representing the created user.

        Raises:
            NextCloudUserExistsError: If the user already exists.
            NextCloudAuthError: If admin credentials are invalid.
            NextCloudConnectionError: If unable to connect.
            NextCloudError: For other errors.

        Example:
            >>> user = await client.create_user(
            ...     "johndoe",
            ...     "securepassword123",
            ...     email="john@example.com"
            ... )
            >>> print(f"Created user: {user.user_id}")
        """
        logger.info(f"Creating NextCloud user: {user_id}")

        # Build form data for user creation
        data = {
            "userid": user_id,
            "password": password,
        }

        if email:
            data["email"] = email

        if display_name:
            data["displayName"] = display_name

        await self._request("POST", "/ocs/v1.php/cloud/users", data=data)

        logger.info(f"Successfully created NextCloud user: {user_id}")

        return NextCloudUser(
            user_id=user_id,
            email=email,
            display_name=display_name or user_id,
        )

    async def get_user(self, user_id: str) -> Optional[NextCloudUser]:
        """
        Get information about a user.

        Args:
            user_id: The username to look up.

        Returns:
            NextCloudUser if found, None if user doesn't exist.

        Example:
            >>> user = await client.get_user("john")
            >>> if user:
            ...     print(f"Email: {user.email}")
        """
        try:
            data = await self._request("GET", f"/ocs/v1.php/cloud/users/{user_id}")
            user_data = data.get("ocs", {}).get("data", {})

            if not user_data:
                return None

            return NextCloudUser(
                user_id=user_data.get("id", user_id),
                email=user_data.get("email"),
                display_name=user_data.get("displayname"),
            )
        except NextCloudError:
            return None

    async def set_password(self, user_id: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Args:
            user_id: The username of the user to update.
            new_password: The new password to set.

        Returns:
            True if the password was successfully set.

        Raises:
            NextCloudError: If the user doesn't exist or update fails.
            NextCloudAuthError: If admin credentials are invalid.
            NextCloudConnectionError: If unable to connect.

        Example:
            >>> await client.set_password("john", "newSecurePassword123")
        """
        logger.info(f"Setting password for NextCloud user: {user_id}")

        # NextCloud OCS API: PUT /ocs/v1.php/cloud/users/{userid}
        # with key=password and value=new_password
        await self._request(
            "PUT",
            f"/ocs/v1.php/cloud/users/{user_id}",
            data={
                "key": "password",
                "value": new_password,
            },
        )

        logger.info(f"Successfully set password for NextCloud user: {user_id}")
        return True


# =============================================================================
# NextCloud Service (Multi-URL Failover)
# =============================================================================


class NextCloudService:
    """
    High-level NextCloud service with multi-URL failover support.

    This service wraps NextCloudClient and provides automatic failover
    between multiple NextCloud server URLs. URLs are tried in order during
    health checks, and the working URL is cached for subsequent API calls.

    Key behaviors:
        - Health checks always start from the top of the URL list, preferring
          the primary server when it recovers from an outage.
        - Other API calls use the cached active URL for efficiency.
        - If no URL has been resolved yet, API calls trigger URL resolution.

    Attributes:
        urls: List of NextCloud server URLs to try, in priority order.
        admin_user: Admin username for authentication.
        admin_password: Admin password for authentication.
        active_url: The currently active (working) URL, or None if not yet resolved.

    Example:
        >>> service = NextCloudService(
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
        - NextCloudClient: Low-level single-URL client used internally.
        - bot.config.NextCloudConfig: Configuration with URL list.
    """

    def __init__(self, urls: list[str], admin_user: str, admin_password: str) -> None:
        """
        Initialize the NextCloud service.

        Args:
            urls: List of NextCloud server URLs to try, in priority order.
                The first URL is considered the "primary" and is preferred
                when available. Each URL should be a base URL like
                "https://nextcloud.example.com" (trailing slashes are stripped).
            admin_user: Admin username for OCS API authentication.
            admin_password: Admin password for OCS API authentication.
        """
        self.urls = [url.rstrip("/") for url in urls]
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._active_url: str | None = None
        self._client: NextCloudClient | None = None

    @property
    def active_url(self) -> str | None:
        """
        Get the currently active (working) URL.

        Returns:
            The URL that successfully passed the last health check,
            or None if no URL has been resolved yet.
        """
        return self._active_url

    async def _ensure_client(self) -> NextCloudClient:
        """
        Ensure we have a working client, resolving URL if needed.

        If no active URL is set, triggers URL resolution by trying
        each URL in order until one responds successfully.

        Returns:
            A NextCloudClient connected to the active URL.

        Raises:
            NextCloudError: If no URLs are configured or all URLs fail.
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
            NextCloudConnectionError: If all URLs fail to connect.
            NextCloudError: If no URLs are configured.

        Example:
            >>> url = await service.resolve_url()
            >>> print(f"Using {url}")
        """
        if not self.urls:
            raise NextCloudError("No NextCloud URLs configured")

        errors: list[str] = []

        for url in self.urls:
            logger.debug(f"Trying NextCloud URL: {url}")
            client = NextCloudClient(
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
                logger.info(f"NextCloud URL resolved: {url}")
                return url

            except NextCloudConnectionError as e:
                logger.warning(f"Failed to connect to {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

            except NextCloudError as e:
                logger.warning(f"NextCloud error at {url}: {e}")
                errors.append(f"{url}: {e}")
                await client.close()

        # All URLs failed
        error_summary = "; ".join(errors)
        raise NextCloudConnectionError(f"All NextCloud URLs failed: {error_summary}")

    async def check_health(self) -> bool:
        """
        Check NextCloud server health, starting from the primary URL.

        Unlike other API methods that use the cached active URL, health
        checks always start from the top of the URL list. This ensures
        that when the primary server recovers from an outage, subsequent
        health checks will detect this and switch back to it.

        Returns:
            True if the server is healthy.

        Raises:
            NextCloudConnectionError: If all URLs fail to connect.
            NextCloudAuthError: If authentication fails on all URLs.
            NextCloudError: If all URLs return errors.

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

    async def user_exists(self, user_id: str) -> bool:
        """
        Check if a user exists in NextCloud.

        Delegates to the underlying NextCloudClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NextCloudClient.user_exists for full documentation.
        """
        client = await self._ensure_client()
        return await client.user_exists(user_id)

    async def create_user(
        self,
        user_id: str,
        password: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> NextCloudUser:
        """
        Create a new user in NextCloud.

        Delegates to the underlying NextCloudClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NextCloudClient.create_user for full documentation.
        """
        client = await self._ensure_client()
        return await client.create_user(
            user_id=user_id,
            password=password,
            email=email,
            display_name=display_name,
        )

    async def get_user(self, user_id: str) -> Optional[NextCloudUser]:
        """
        Get information about a user.

        Delegates to the underlying NextCloudClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NextCloudClient.get_user for full documentation.
        """
        client = await self._ensure_client()
        return await client.get_user(user_id)

    async def set_password(self, user_id: str, new_password: str) -> bool:
        """
        Set a new password for an existing user.

        Delegates to the underlying NextCloudClient using the cached
        active URL. If no URL is cached, triggers URL resolution first.

        See NextCloudClient.set_password for full documentation.
        """
        client = await self._ensure_client()
        return await client.set_password(user_id, new_password)

    async def close(self) -> None:
        """
        Close the service and release resources.

        Closes the underlying NextCloudClient's HTTP session. Safe to call
        multiple times or if no client was ever created.
        """
        if self._client:
            await self._client.close()
            self._client = None
        self._active_url = None

    async def __aenter__(self) -> "NextCloudService":
        """Support async context manager usage."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close on context manager exit."""
        await self.close()

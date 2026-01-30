"""
Minecraft server status client and service for MonolithBot.

This module provides an async client for querying Minecraft Java Edition servers
using the Server List Ping (SLP) protocol, as well as a service layer that handles
multi-URL failover and tracks server state across multiple instances.

Key Features:
    - Async/await support using mcstatus library
    - Multi-URL failover support per server instance
    - Multiple server instance tracking
    - Player join detection via polling
    - Graceful handling of servers with hidden player lists

Architecture:
    - MinecraftClient: Low-level client for a single Minecraft server address
    - MinecraftService: High-level service managing multiple servers with failover

Protocol Used:
    - Server List Ping (SLP) - Same protocol Minecraft clients use for server list

Example:
    >>> from bot.services.minecraft import MinecraftService
    >>> from bot.config import MinecraftServerConfig
    >>>
    >>> # Create service with multiple server instances
    >>> servers = [
    ...     MinecraftServerConfig(name="Survival", urls=["mc.example.com:25565"]),
    ...     MinecraftServerConfig(name="Creative", urls=["creative.example.com"]),
    ... ]
    >>> service = MinecraftService(servers)
    >>>
    >>> # Check health of a specific server (with failover)
    >>> status = await service.check_health("Survival")
    >>> print(f"{status.player_count}/{status.max_players} players online")
    >>>
    >>> # Get state for player tracking
    >>> state = service.get_server_state("Survival")
    >>> print(f"Active URL: {state.active_url}")

See Also:
    - mcstatus docs: https://github.com/py-mine/mcstatus
    - bot.cogs.minecraft.health: Uses this service for health monitoring
    - bot.cogs.minecraft.players: Uses this service for player announcements
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mcstatus import JavaServer

from bot.config import MinecraftServerConfig

# Module logger
logger = logging.getLogger("monolithbot.minecraft")


# =============================================================================
# Exceptions
# =============================================================================


class MinecraftError(Exception):
    """
    Base exception for all Minecraft-related errors.

    This is the parent class for more specific Minecraft errors.
    Catch this to handle any Minecraft operation failure.
    """

    pass


class MinecraftConnectionError(MinecraftError):
    """
    Raised when unable to connect to a Minecraft server.

    This typically means:
        - Server is offline or unreachable
        - Network connectivity issues
        - Firewall blocking the connection
        - Invalid hostname/port
    """

    pass


class MinecraftTimeoutError(MinecraftError):
    """
    Raised when a Minecraft server query times out.

    This may indicate:
        - Server is overloaded
        - Network latency issues
        - Server is starting up
    """

    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class MinecraftServerStatus:
    """
    Represents the current status of a Minecraft server.

    This class contains all information retrieved from a Server List Ping query.

    Attributes:
        online: Whether the server responded successfully.
        player_count: Number of players currently online.
        max_players: Maximum player capacity.
        player_names: Set of online player names (may be empty if server hides list).
        players_hidden: True if server is configured to hide player list.
        motd: Message of the Day (server description).
        version: Minecraft version string (e.g., "1.20.4").
        latency_ms: Round-trip time in milliseconds.

    Example:
        >>> status = MinecraftServerStatus(
        ...     online=True,
        ...     player_count=5,
        ...     max_players=20,
        ...     player_names={"Steve", "Alex"},
        ...     motd="Welcome to my server!",
        ...     version="1.20.4",
        ...     latency_ms=45.2,
        ... )
    """

    online: bool
    player_count: int = 0
    max_players: int = 0
    player_names: set[str] = field(default_factory=set)
    players_hidden: bool = False
    motd: str = ""
    version: str = ""
    latency_ms: float = 0.0


@dataclass
class MinecraftServerState:
    """
    Tracks the state of a single Minecraft server instance over time.

    This class maintains both configuration and runtime state for a server,
    including health status, active URL, and player tracking for join detection.

    Attributes:
        name: Display name for this server.
        urls: List of server addresses to try (for failover).
        active_url: Currently connected URL (None if never connected).
        online: Current online status (None = unknown, True = online, False = offline).
        last_online: Timestamp when server was last confirmed online.
        went_offline: Timestamp when server went offline (for downtime calculation).
        previous_players: Set of player names from last check (for join detection).
        last_status: Most recent status response (for display purposes).

    Example:
        >>> state = MinecraftServerState(
        ...     name="Survival",
        ...     urls=["mc.example.com:25565", "backup.example.com:25565"],
        ... )
        >>> # After health check
        >>> state.online = True
        >>> state.active_url = "mc.example.com:25565"
    """

    name: str
    urls: list[str]
    active_url: Optional[str] = None
    online: Optional[bool] = None  # None = unknown, True = online, False = offline
    last_online: Optional[datetime] = None
    went_offline: Optional[datetime] = None
    previous_players: set[str] = field(default_factory=set)
    last_status: Optional[MinecraftServerStatus] = None


# =============================================================================
# Minecraft Client (Single Server)
# =============================================================================


class MinecraftClient:
    """
    Low-level async client for querying a single Minecraft server.

    This class wraps the mcstatus library to provide a consistent interface
    for querying Minecraft Java Edition servers using the Server List Ping protocol.

    The client handles:
        - Async status queries
        - Parsing player information
        - Handling servers with hidden player lists
        - Timeout management

    Attributes:
        address: Server address in "host:port" or "host" format.
        timeout: Query timeout in seconds (default: 5).

    Example:
        >>> client = MinecraftClient("mc.example.com:25565")
        >>> status = await client.check_status()
        >>> print(f"Online: {status.online}, Players: {status.player_count}")
    """

    DEFAULT_PORT = 25565
    DEFAULT_TIMEOUT = 5.0

    def __init__(self, address: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        """
        Initialize a Minecraft client for a single server address.

        Args:
            address: Server address in "host:port" or "host" format.
                If port is omitted, defaults to 25565.
            timeout: Query timeout in seconds.
        """
        self.address = address
        self.timeout = timeout
        self._server: Optional[JavaServer] = None

    def _get_server(self) -> JavaServer:
        """Get or create the JavaServer instance."""
        if self._server is None:
            self._server = JavaServer.lookup(self.address)
        return self._server

    async def check_status(self) -> MinecraftServerStatus:
        """
        Query the Minecraft server for its current status.

        This performs a Server List Ping query to retrieve server information
        including player count, MOTD, version, and optionally player names.

        Returns:
            MinecraftServerStatus with server information.

        Raises:
            MinecraftConnectionError: If unable to connect to the server.
            MinecraftTimeoutError: If the query times out.
            MinecraftError: For other query failures.

        Example:
            >>> client = MinecraftClient("mc.example.com")
            >>> try:
            ...     status = await client.check_status()
            ...     print(f"{status.player_count} players online")
            ... except MinecraftConnectionError:
            ...     print("Server is offline")
        """
        try:
            server = self._get_server()
            response = await server.async_status()

            # Extract player names if available
            player_names: set[str] = set()
            players_hidden = False

            if response.players.sample:
                player_names = {p.name for p in response.players.sample if p.name}
            elif response.players.online > 0:
                # Server has players but didn't provide sample - likely hidden
                players_hidden = True

            # Parse MOTD - can be string or complex object
            motd = ""
            if response.motd:
                if hasattr(response.motd, "raw"):
                    # Handle MOTD as parsed object
                    motd = str(response.motd.raw)
                elif isinstance(response.motd, str):
                    motd = response.motd
                else:
                    # Fallback: convert to string
                    motd = str(response.motd)

            # Clean up MOTD (remove color codes if present)
            motd = self._clean_motd(motd)

            return MinecraftServerStatus(
                online=True,
                player_count=response.players.online,
                max_players=response.players.max,
                player_names=player_names,
                players_hidden=players_hidden,
                motd=motd,
                version=response.version.name,
                latency_ms=response.latency,
            )

        except TimeoutError as e:
            logger.debug(f"Timeout querying {self.address}: {e}")
            raise MinecraftTimeoutError(f"Query timed out for {self.address}") from e

        except OSError as e:
            # Connection refused, network unreachable, etc.
            logger.debug(f"Connection error for {self.address}: {e}")
            raise MinecraftConnectionError(
                f"Cannot connect to {self.address}: {e}"
            ) from e

        except Exception as e:
            # Catch-all for other mcstatus errors
            logger.debug(f"Error querying {self.address}: {e}")
            raise MinecraftError(f"Failed to query {self.address}: {e}") from e

    @staticmethod
    def _clean_motd(motd: str) -> str:
        """
        Clean up MOTD by removing Minecraft color/formatting codes.

        Minecraft uses § followed by a character for formatting codes.
        This removes them for cleaner display in Discord.

        Args:
            motd: Raw MOTD string potentially containing formatting codes.

        Returns:
            Cleaned MOTD string.
        """
        import re

        # Remove §X color codes and common formatting
        cleaned = re.sub(r"§[0-9a-fklmnor]", "", motd, flags=re.IGNORECASE)
        # Also handle {"text": ...} style if present
        if cleaned.startswith("{") and "text" in cleaned:
            try:
                import json

                data = json.loads(cleaned)
                if isinstance(data, dict) and "text" in data:
                    cleaned = data["text"]
            except (json.JSONDecodeError, KeyError):
                pass
        return cleaned.strip()


# =============================================================================
# Minecraft Service (Multi-Server with Failover)
# =============================================================================


class MinecraftService:
    """
    High-level service for managing multiple Minecraft server instances.

    This service provides:
        - Multi-URL failover per server (try backup URLs if primary fails)
        - State tracking for each server instance
        - Player join detection via set differencing

    The service maintains a MinecraftServerState for each configured server,
    tracking online status, active URL, and player lists over time.

    Attributes:
        servers: Dictionary mapping server names to their state objects.

    Example:
        >>> from bot.config import MinecraftServerConfig
        >>>
        >>> configs = [
        ...     MinecraftServerConfig(name="Survival", urls=["mc1.example.com"]),
        ...     MinecraftServerConfig(name="Creative", urls=["mc2.example.com"]),
        ... ]
        >>> service = MinecraftService(configs)
        >>>
        >>> # Check health with automatic failover
        >>> status = await service.check_health("Survival")
        >>>
        >>> # Get all server states
        >>> for state in service.get_all_servers():
        ...     print(f"{state.name}: {'Online' if state.online else 'Offline'}")
    """

    def __init__(self, servers: list[MinecraftServerConfig]) -> None:
        """
        Initialize the Minecraft service with server configurations.

        Args:
            servers: List of MinecraftServerConfig objects defining
                the servers to monitor.
        """
        self._servers: dict[str, MinecraftServerState] = {}

        for server_config in servers:
            self._servers[server_config.name] = MinecraftServerState(
                name=server_config.name,
                urls=list(server_config.urls),
            )

        logger.info(f"MinecraftService initialized with {len(self._servers)} servers")

    # -------------------------------------------------------------------------
    # Server Access
    # -------------------------------------------------------------------------

    def get_server_state(self, server_name: str) -> Optional[MinecraftServerState]:
        """
        Get the state object for a specific server.

        Args:
            server_name: Name of the server to retrieve.

        Returns:
            MinecraftServerState for the server, or None if not found.
        """
        return self._servers.get(server_name)

    def get_all_servers(self) -> list[MinecraftServerState]:
        """
        Get state objects for all configured servers.

        Returns:
            List of all MinecraftServerState objects.
        """
        return list(self._servers.values())

    def get_server_names(self) -> list[str]:
        """
        Get names of all configured servers.

        Returns:
            List of server names.
        """
        return list(self._servers.keys())

    # -------------------------------------------------------------------------
    # Health Checking with Failover
    # -------------------------------------------------------------------------

    async def check_health(self, server_name: str) -> MinecraftServerStatus:
        """
        Check health of a server, trying URLs in order (failover).

        This method tries each configured URL for the server in order,
        returning the first successful response. The working URL is cached
        in the server's state for subsequent queries.

        Unlike regular status checks, health checks always start from the
        primary (first) URL to detect when a failed primary recovers.

        Args:
            server_name: Name of the server to check.

        Returns:
            MinecraftServerStatus from the first responding URL.

        Raises:
            MinecraftError: If server name is not found.
            MinecraftConnectionError: If all URLs fail to connect.
        """
        state = self._servers.get(server_name)
        if state is None:
            raise MinecraftError(f"Unknown server: {server_name}")

        if not state.urls:
            raise MinecraftError(f"No URLs configured for server: {server_name}")

        errors: list[str] = []

        # Always try URLs from the beginning for health checks
        for url in state.urls:
            logger.debug(f"Trying {server_name} at {url}")
            client = MinecraftClient(url)

            try:
                status = await client.check_status()

                # Success! Update state
                state.active_url = url
                state.last_status = status
                logger.info(f"Server {server_name} online at {url}")

                return status

            except MinecraftConnectionError as e:
                logger.warning(f"Connection failed for {server_name} at {url}: {e}")
                errors.append(f"{url}: {e}")

            except MinecraftTimeoutError as e:
                logger.warning(f"Timeout for {server_name} at {url}: {e}")
                errors.append(f"{url}: {e}")

            except MinecraftError as e:
                logger.warning(f"Error for {server_name} at {url}: {e}")
                errors.append(f"{url}: {e}")

        # All URLs failed
        error_summary = "; ".join(errors)
        raise MinecraftConnectionError(
            f"All URLs failed for {server_name}: {error_summary}"
        )

    async def get_status(self, server_name: str) -> MinecraftServerStatus:
        """
        Get current status of a server using cached active URL.

        Unlike check_health(), this method uses the previously cached
        active URL if available, only falling back to full failover
        if no URL is cached or the cached URL fails.

        This is more efficient for frequent status checks when the
        server is known to be stable.

        Args:
            server_name: Name of the server to query.

        Returns:
            MinecraftServerStatus from the server.

        Raises:
            MinecraftError: If server name is not found.
            MinecraftConnectionError: If unable to connect.
        """
        state = self._servers.get(server_name)
        if state is None:
            raise MinecraftError(f"Unknown server: {server_name}")

        # Try cached URL first
        if state.active_url:
            try:
                client = MinecraftClient(state.active_url)
                status = await client.check_status()
                state.last_status = status
                return status
            except MinecraftError:
                logger.info(
                    f"Cached URL {state.active_url} failed for {server_name}, "
                    "trying failover"
                )

        # Fall back to full health check with failover
        return await self.check_health(server_name)

    # -------------------------------------------------------------------------
    # Player Tracking
    # -------------------------------------------------------------------------

    def detect_player_joins(
        self, server_name: str, current_players: set[str]
    ) -> set[str]:
        """
        Detect which players have joined since the last check.

        This compares the current player set against the previously stored
        set and returns the difference (new players). The previous players
        set is then updated with the current players.

        Args:
            server_name: Name of the server.
            current_players: Set of currently online player names.

        Returns:
            Set of player names that joined since last check.
            Empty set if server not found or on first check.
        """
        state = self._servers.get(server_name)
        if state is None:
            return set()

        # Find new players (in current but not in previous)
        new_players = current_players - state.previous_players

        # Update stored players for next comparison
        state.previous_players = current_players.copy()

        return new_players

    def detect_player_leaves(
        self, server_name: str, current_players: set[str]
    ) -> set[str]:
        """
        Detect which players have left since the last check.

        Args:
            server_name: Name of the server.
            current_players: Set of currently online player names.

        Returns:
            Set of player names that left since last check.
            Empty set if server not found or on first check.

        Note:
            This does NOT update the previous_players set.
            Call detect_player_joins() to update state.
        """
        state = self._servers.get(server_name)
        if state is None:
            return set()

        # Find players who left (in previous but not in current)
        return state.previous_players - current_players

    def update_players(self, server_name: str, current_players: set[str]) -> None:
        """
        Update the stored player set without detecting changes.

        Use this for initial player list setup or when you don't
        need join/leave detection.

        Args:
            server_name: Name of the server.
            current_players: Set of currently online player names.
        """
        state = self._servers.get(server_name)
        if state:
            state.previous_players = current_players.copy()

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def mark_online(self, server_name: str) -> None:
        """
        Mark a server as online and update timestamps.

        Args:
            server_name: Name of the server.
        """
        state = self._servers.get(server_name)
        if state:
            state.online = True
            state.last_online = datetime.now(timezone.utc)
            state.went_offline = None

    def mark_offline(self, server_name: str) -> None:
        """
        Mark a server as offline and record the time.

        Args:
            server_name: Name of the server.
        """
        state = self._servers.get(server_name)
        if state:
            was_online = state.online
            state.online = False
            if was_online is True or was_online is None:
                state.went_offline = datetime.now(timezone.utc)

    def get_downtime(self, server_name: str) -> Optional[float]:
        """
        Get the current downtime duration in seconds.

        Args:
            server_name: Name of the server.

        Returns:
            Downtime in seconds, or None if server is online or never went offline.
        """
        state = self._servers.get(server_name)
        if state and state.went_offline and state.online is False:
            return (datetime.now(timezone.utc) - state.went_offline).total_seconds()
        return None

    def reset_state(self, server_name: str) -> None:
        """
        Reset a server's runtime state (not configuration).

        This clears online status, timestamps, and player tracking
        while preserving name and URLs.

        Args:
            server_name: Name of the server.
        """
        state = self._servers.get(server_name)
        if state:
            state.active_url = None
            state.online = None
            state.last_online = None
            state.went_offline = None
            state.previous_players = set()
            state.last_status = None

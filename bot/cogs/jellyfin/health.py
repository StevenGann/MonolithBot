"""
Jellyfin health monitoring cog for server status.

This cog provides continuous monitoring of the Jellyfin server's availability,
sending Discord notifications when the server goes offline or comes back online.

Key Features:
    - Periodic health checks at configurable intervals
    - State-based notifications (only alerts on status changes)
    - Downtime tracking and reporting
    - Rich Discord embeds with server details

State Machine:
    The cog tracks server state to avoid notification spam:

    ```
    [Unknown] ──check──▶ [Online]  ◀──────────────────┐
        │                   │                         │
        │                   │ check fails             │ check succeeds
        │                   ▼                         │
        │              [Offline] ─────────────────────┘
        │                   │
        └───check fails────►│
                            │
                   (notification sent only on
                    state transitions, not
                    on every failed check)
    ```

Configuration:
    Uses these settings from bot.config.jellyfin.schedule:
        - health_check_interval_minutes: How often to check (default: 5)

    And from bot.config.discord:
        - alert_channel_id: Where to send status notifications

Example Notifications:
    - 🔴 "Jellyfin Server Offline" - When server becomes unreachable
    - 🟢 "Jellyfin Server Online" - When server recovers (includes downtime)

See Also:
    - bot.services.jellyfin: The API client used for health checks
    - bot.cogs.jellyfin.announcements: Companion cog for content announcements
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import discord
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from bot.services.jellyfin import (
    JellyfinConnectionError,
    JellyfinError,
    ServerInfo,
)
from bot.services.scheduler import create_scheduler

if TYPE_CHECKING:
    from bot.main import MonolithBot

# Module logger
logger = logging.getLogger("monolithbot.jellyfin.health")


class JellyfinHealthCog(commands.Cog, name="JellyfinHealth"):
    """
    Discord cog for monitoring Jellyfin server health.

    This cog performs periodic health checks against the Jellyfin server
    and sends notifications to a Discord channel when the server status
    changes (online → offline or offline → online).

    The cog maintains internal state to track:
        - Current server status (online/offline/unknown)
        - When the server was last seen online
        - When the server went offline (for downtime calculation)
        - Last known server info (name, version)

    Attributes:
        bot: Reference to the MonolithBot instance.
        scheduler: APScheduler instance for periodic checks.

    Note:
        This cog uses the shared `bot.jellyfin_service` for API calls,
        which handles multi-URL failover automatically.

    Example:
        The cog is automatically loaded by the bot. To manually interact:

        >>> # Cog is loaded automatically, but can be accessed via:
        >>> health_cog = bot.get_cog("JellyfinHealth")
    """

    def __init__(self, bot: "MonolithBot") -> None:
        """
        Initialize the health monitoring cog.

        Args:
            bot: The MonolithBot instance. Used to access configuration,
                shared services, and Discord channels.
        """
        self.bot = bot
        self.scheduler = create_scheduler(bot.config)

        # State tracking for server status
        # None = unknown (initial state before first check)
        # True = server is online
        # False = server is offline
        self._server_online: Optional[bool] = None

        # Timestamp tracking for status reporting
        self._last_online: Optional[datetime] = None
        self._went_offline: Optional[datetime] = None
        self._last_server_info: Optional[ServerInfo] = None

    # -------------------------------------------------------------------------
    # Cog Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Called automatically by discord.py when the cog is added to the bot.
        Performs an initial health check to establish baseline state, and
        starts the periodic health check scheduler.

        Note:
            Uses the shared `bot.jellyfin_service` instead of creating
            a separate client - the service handles multi-URL failover.
        """
        # Establish initial state (don't notify on startup)
        await self._initial_health_check()

        # Schedule periodic health checks
        interval_minutes = self.bot.config.jellyfin.schedule.health_check_interval_minutes
        self.scheduler.add_job(
            self._run_health_check,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="jellyfin_health_check",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            f"Jellyfin health monitoring started (checking every {interval_minutes} minutes)"
        )

    async def cog_unload(self) -> None:
        """
        Clean up resources when the cog is unloaded.

        Called automatically by discord.py when the cog is removed from the bot.
        Stops the scheduler. Note: The Jellyfin service is managed by the bot,
        not the cog, so we don't close it here.
        """
        self.scheduler.shutdown(wait=False)
        logger.info("Jellyfin health monitoring cog unloaded")

    # -------------------------------------------------------------------------
    # Health Check Logic
    # -------------------------------------------------------------------------

    async def _initial_health_check(self) -> None:
        """
        Perform initial health check to establish baseline server state.

        This check runs once at startup to determine the initial state
        without sending notifications. This prevents spurious "server online"
        notifications every time the bot restarts.
        """
        try:
            self._last_server_info = await self.bot.jellyfin_service.check_health()
            self._server_online = True
            self._last_online = datetime.now(timezone.utc)
            logger.info(
                f"Initial health check passed - "
                f"Server: {self._last_server_info.server_name} "
                f"v{self._last_server_info.version} "
                f"(via {self.bot.jellyfin_service.active_url})"
            )
        except JellyfinError as e:
            self._server_online = False
            self._went_offline = datetime.now(timezone.utc)
            logger.warning(f"Initial health check failed: {e}")

    async def _run_health_check(self) -> None:
        """
        Execute a scheduled health check and handle state changes.

        This is the main health check method called by the scheduler.
        It attempts to contact the Jellyfin server and delegates to
        the appropriate handler based on success or failure.

        Note:
            The shared JellyfinService.check_health() always starts from
            the top of the URL list, preferring the primary server when
            it recovers from an outage.

        State transitions trigger notifications:
            - online → offline: Sends offline notification
            - offline → online: Sends online notification with downtime
            - online → online: No notification (silent success)
            - offline → offline: No notification (still down)
        """
        logger.debug("Running Jellyfin health check...")

        try:
            server_info = await self.bot.jellyfin_service.check_health()
            self._last_server_info = server_info
            await self._handle_server_online(server_info)

        except JellyfinConnectionError as e:
            # Network-level failure (can't reach server)
            logger.warning(f"Health check failed - connection error: {e}")
            await self._handle_server_offline(str(e))

        except JellyfinError as e:
            # Server reachable but returned an error
            logger.warning(f"Health check failed - API error: {e}")
            await self._handle_server_offline(str(e))

    async def _handle_server_online(self, server_info: ServerInfo) -> None:
        """
        Handle a successful health check (server is online).

        Updates internal state and sends a notification if the server
        was previously offline (recovery notification).

        Args:
            server_info: Server information from the health check.
        """
        was_offline = self._server_online is False

        # Update state
        self._server_online = True
        self._last_online = datetime.now(timezone.utc)

        # Only notify if this is a recovery (was offline, now online)
        if was_offline:
            # Calculate downtime if we know when it went offline
            downtime: Optional[timedelta] = None
            if self._went_offline:
                downtime = datetime.now(timezone.utc) - self._went_offline
                self._went_offline = None

            logger.info(
                f"Server came back online - {server_info.server_name} "
                f"v{server_info.version}"
            )
            await self._send_online_notification(server_info, downtime)

    async def _handle_server_offline(self, error_message: str) -> None:
        """
        Handle a failed health check (server is offline).

        Updates internal state and sends a notification if this is
        a new outage (was online or unknown, now offline).

        Args:
            error_message: Description of why the health check failed.
        """
        # Check if this is a new outage
        # Notify if: was online (True) or was unknown (None, first check failed)
        was_online = self._server_online is True or self._server_online is None

        if was_online:
            # Record when the outage started
            self._went_offline = datetime.now(timezone.utc)
            self._server_online = False
            logger.warning(f"Server went offline: {error_message}")
            await self._send_offline_notification(error_message)
        else:
            # Server was already offline, no need to notify again
            logger.debug("Server still offline")

    # -------------------------------------------------------------------------
    # Discord Notifications
    # -------------------------------------------------------------------------

    async def _send_online_notification(
        self,
        server_info: ServerInfo,
        downtime: Optional[timedelta] = None,
    ) -> None:
        """
        Send a Discord notification that the server is back online.

        Creates a green embed with server details and downtime duration
        (if available).

        Args:
            server_info: Information about the recovered server.
            downtime: How long the server was offline (None if unknown).
        """
        channel = self.bot.get_channel(self.bot.config.discord.alert_channel_id)
        if channel is None:
            logger.error("Alert channel not found")
            return

        embed = discord.Embed(
            title="🟢 Jellyfin Server Online",
            description="The Jellyfin server is back online and responding!",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(name="Server", value=server_info.server_name, inline=True)
        embed.add_field(name="Version", value=server_info.version, inline=True)

        if downtime:
            downtime_str = self._format_duration(downtime.total_seconds())
            embed.add_field(name="Downtime", value=downtime_str, inline=True)

        embed.set_footer(text="Monolith Status")

        await channel.send(embed=embed)
        logger.info("Sent server online notification")

    async def _send_offline_notification(self, error_message: str) -> None:
        """
        Send a Discord notification that the server is offline.

        Creates a red embed with error details and last known online time.

        Args:
            error_message: Description of the connection/API error.
        """
        channel = self.bot.get_channel(self.bot.config.discord.alert_channel_id)
        if channel is None:
            logger.error("Alert channel not found")
            return

        embed = discord.Embed(
            title="🔴 Jellyfin Server Offline",
            description="The Jellyfin server is not responding!",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )

        # Show error in a code block (truncate if too long)
        embed.add_field(
            name="Error",
            value=f"```{error_message[:500]}```",
            inline=False,
        )

        # Show configured URLs
        urls = self.bot.config.jellyfin.urls
        if len(urls) > 1:
            url_list = "\n".join(f"• {url}" for url in urls)
            embed.add_field(
                name=f"URLs Tried ({len(urls)})",
                value=url_list,
                inline=False,
            )
        else:
            embed.add_field(
                name="Server URL",
                value=self.bot.config.jellyfin.url,
                inline=False,
            )

        # Show relative time since last successful check
        if self._last_online:
            embed.add_field(
                name="Last Online",
                value=f"<t:{int(self._last_online.timestamp())}:R>",
                inline=True,
            )

        embed.set_footer(text="Monolith Status")

        await channel.send(embed=embed)
        logger.info("Sent server offline notification")

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def _format_duration(self, seconds: float) -> str:
        """
        Format a duration in seconds to a human-readable string.

        Automatically selects the most appropriate unit(s) based on
        the duration length.

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable duration string.

        Examples:
            >>> self._format_duration(45)
            '45 seconds'
            >>> self._format_duration(90)
            '1 minute'
            >>> self._format_duration(3665)
            '1h 1m'
            >>> self._format_duration(90000)
            '1d 1h'
        """
        seconds = int(seconds)

        # Less than a minute: show seconds
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"

        # Less than an hour: show minutes
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"

        # Less than a day: show hours (and minutes if non-zero)
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if hours < 24:
            if remaining_minutes:
                return f"{hours}h {remaining_minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"

        # Days: show days (and hours if non-zero)
        days = hours // 24
        remaining_hours = hours % 24
        if remaining_hours:
            return f"{days}d {remaining_hours}h"
        return f"{days} day{'s' if days != 1 else ''}"


# =============================================================================
# Cog Setup
# =============================================================================


async def setup(bot: "MonolithBot") -> None:
    """
    Setup function called by discord.py to load the cog.

    Args:
        bot: The MonolithBot instance to add the cog to.
    """
    await bot.add_cog(JellyfinHealthCog(bot))

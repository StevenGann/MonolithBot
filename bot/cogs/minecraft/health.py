"""
Minecraft health monitoring cog for server status.

This cog provides continuous monitoring of Minecraft server availability,
sending Discord notifications when servers go offline or come back online.

Key Features:
    - Periodic health checks at configurable intervals
    - Multi-server support with independent state tracking
    - Multi-URL failover per server
    - State-based notifications (only alerts on status changes)
    - Downtime tracking and reporting
    - Rich Discord embeds with server details

State Machine:
    Each server tracks its own state independently:

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
    Uses these settings from bot.config.minecraft.schedule:
        - health_check_interval_minutes: How often to check (default: 1)

    And from bot.config.minecraft:
        - alert_channel_id: Where to send status notifications
        - servers: List of servers to monitor

Example Notifications:
    - 🔴 "Survival Server Offline" - When server becomes unreachable
    - 🟢 "Survival Server Online" - When server recovers (includes downtime)

See Also:
    - bot.services.minecraft: The client/service used for health checks
    - bot.cogs.minecraft.players: Companion cog for player announcements
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from bot.services.minecraft import (
    MinecraftConnectionError,
    MinecraftError,
    MinecraftServerStatus,
)
from bot.services.scheduler import create_scheduler

if TYPE_CHECKING:
    from bot.main import MonolithBot

# Module logger
logger = logging.getLogger("monolithbot.minecraft.health")


class MinecraftHealthCog(commands.Cog, name="MinecraftHealth"):
    """
    Discord cog for monitoring Minecraft server health.

    This cog performs periodic health checks against all configured Minecraft
    servers and sends notifications to a Discord channel when server status
    changes (online → offline or offline → online).

    Unlike the Jellyfin health cog which monitors a single service,
    this cog manages multiple independent server instances, each with
    its own state tracking and URL failover.

    Attributes:
        bot: Reference to the MonolithBot instance.
        scheduler: APScheduler instance for periodic checks.

    Note:
        This cog uses the shared `bot.minecraft_service` for status checks,
        which handles multi-URL failover automatically per server.

    Example:
        The cog is automatically loaded by the bot. To manually interact:

        >>> health_cog = bot.get_cog("MinecraftHealth")
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

    # -------------------------------------------------------------------------
    # Cog Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Called automatically by discord.py when the cog is added to the bot.
        Performs initial health checks for all servers to establish baseline
        state, and starts the periodic health check scheduler.
        """
        # Establish initial state for all servers (don't notify on startup)
        await self._initial_health_checks()

        # Schedule periodic health checks
        interval_minutes = (
            self.bot.config.minecraft.schedule.health_check_interval_minutes
        )
        self.scheduler.add_job(
            self._run_health_checks,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="minecraft_health_check",
            replace_existing=True,
        )

        self.scheduler.start()
        server_count = len(self.bot.minecraft_service.get_all_servers())
        logger.info(
            f"Minecraft health monitoring started for {server_count} server(s) "
            f"(checking every {interval_minutes} minute(s))"
        )

    async def cog_unload(self) -> None:
        """
        Clean up resources when the cog is unloaded.

        Called automatically by discord.py when the cog is removed from the bot.
        Stops the scheduler. Note: The Minecraft service is managed by the bot,
        not the cog, so we don't close it here.
        """
        self.scheduler.shutdown(wait=False)
        logger.info("Minecraft health monitoring cog unloaded")

    # -------------------------------------------------------------------------
    # Health Check Logic
    # -------------------------------------------------------------------------

    async def _initial_health_checks(self) -> None:
        """
        Perform initial health checks for all servers to establish baseline state.

        This runs once at startup to determine initial states without sending
        notifications. This prevents spurious "server online" notifications
        every time the bot restarts.
        """
        service = self.bot.minecraft_service

        for server_name in service.get_server_names():
            try:
                status = await service.check_health(server_name)
                service.mark_online(server_name)

                # Initialize player tracking
                service.update_players(server_name, status.player_names)

                state = service.get_server_state(server_name)
                logger.info(
                    f"Initial health check passed for {server_name} - "
                    f"{status.player_count}/{status.max_players} players, "
                    f"v{status.version} (via {state.active_url})"
                )

            except MinecraftError as e:
                service.mark_offline(server_name)
                logger.warning(f"Initial health check failed for {server_name}: {e}")

    async def _run_health_checks(self) -> None:
        """
        Execute scheduled health checks for all configured servers.

        This is the main health check method called by the scheduler.
        It iterates through all servers, performing health checks and
        handling state changes independently for each.
        """
        logger.debug("Running Minecraft health checks...")

        service = self.bot.minecraft_service

        for server_name in service.get_server_names():
            await self._check_server_health(server_name)

    async def _check_server_health(self, server_name: str) -> None:
        """
        Check health of a single server and handle state changes.

        Args:
            server_name: Name of the server to check.
        """
        service = self.bot.minecraft_service
        state = service.get_server_state(server_name)

        if state is None:
            logger.error(f"Unknown server in health check: {server_name}")
            return

        try:
            status = await service.check_health(server_name)
            await self._handle_server_online(server_name, status)

        except MinecraftConnectionError as e:
            logger.warning(f"Health check failed for {server_name} - connection: {e}")
            await self._handle_server_offline(server_name, str(e))

        except MinecraftError as e:
            logger.warning(f"Health check failed for {server_name} - error: {e}")
            await self._handle_server_offline(server_name, str(e))

    async def _handle_server_online(
        self, server_name: str, status: MinecraftServerStatus
    ) -> None:
        """
        Handle a successful health check (server is online).

        Updates internal state and sends a notification if the server
        was previously offline (recovery notification).

        Args:
            server_name: Name of the server.
            status: Status information from the health check.
        """
        service = self.bot.minecraft_service
        state = service.get_server_state(server_name)

        if state is None:
            return

        was_offline = state.online is False

        # Calculate downtime before updating state
        downtime: Optional[timedelta] = None
        if was_offline and state.went_offline:
            downtime = datetime.now(timezone.utc) - state.went_offline

        # Update state
        service.mark_online(server_name)

        # Only notify if this is a recovery (was offline, now online)
        if was_offline:
            logger.info(
                f"Server {server_name} came back online - "
                f"{status.player_count}/{status.max_players} players, "
                f"v{status.version}"
            )
            await self._send_online_notification(server_name, status, downtime)

    async def _handle_server_offline(
        self, server_name: str, error_message: str
    ) -> None:
        """
        Handle a failed health check (server is offline).

        Updates internal state and sends a notification if this is
        a new outage (was online or unknown, now offline).

        Args:
            server_name: Name of the server.
            error_message: Description of why the health check failed.
        """
        service = self.bot.minecraft_service
        state = service.get_server_state(server_name)

        if state is None:
            return

        # Check if this is a new outage
        was_online = state.online is True or state.online is None

        if was_online:
            service.mark_offline(server_name)
            logger.warning(f"Server {server_name} went offline: {error_message}")
            await self._send_offline_notification(server_name, error_message)
        else:
            logger.debug(f"Server {server_name} still offline")

    # -------------------------------------------------------------------------
    # Discord Notifications
    # -------------------------------------------------------------------------

    async def _send_online_notification(
        self,
        server_name: str,
        status: MinecraftServerStatus,
        downtime: Optional[timedelta] = None,
    ) -> None:
        """
        Send a Discord notification that a server is back online.

        Creates a green embed with server details and downtime duration.

        Args:
            server_name: Name of the recovered server.
            status: Status information from the server.
            downtime: How long the server was offline (None if unknown).
        """
        channel = self.bot.get_channel(self.bot.config.minecraft.alert_channel_id)
        if channel is None:
            logger.error("Minecraft alert channel not found")
            return

        embed = discord.Embed(
            title=f"🟢 {server_name} Server Online",
            description=f"The {server_name} Minecraft server is back online!",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )

        # Server info
        embed.add_field(name="Version", value=status.version, inline=True)
        embed.add_field(
            name="Players",
            value=f"{status.player_count}/{status.max_players}",
            inline=True,
        )

        if downtime:
            downtime_str = self._format_duration(downtime.total_seconds())
            embed.add_field(name="Downtime", value=downtime_str, inline=True)

        if status.motd:
            embed.add_field(name="MOTD", value=status.motd[:256], inline=False)

        # Show active URL
        state = self.bot.minecraft_service.get_server_state(server_name)
        if state and state.active_url:
            embed.add_field(name="Address", value=f"`{state.active_url}`", inline=False)

        embed.set_footer(text="Minecraft Server Status")

        await channel.send(embed=embed)
        logger.info(f"Sent online notification for {server_name}")

    async def _send_offline_notification(
        self, server_name: str, error_message: str
    ) -> None:
        """
        Send a Discord notification that a server is offline.

        Creates a red embed with error details and server information.

        Args:
            server_name: Name of the offline server.
            error_message: Description of the connection error.
        """
        channel = self.bot.get_channel(self.bot.config.minecraft.alert_channel_id)
        if channel is None:
            logger.error("Minecraft alert channel not found")
            return

        embed = discord.Embed(
            title=f"🔴 {server_name} Server Offline",
            description=f"The {server_name} Minecraft server is not responding!",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )

        # Show error in a code block
        embed.add_field(
            name="Error",
            value=f"```{error_message[:500]}```",
            inline=False,
        )

        # Show configured URLs
        state = self.bot.minecraft_service.get_server_state(server_name)
        if state:
            if len(state.urls) > 1:
                url_list = "\n".join(f"• {url}" for url in state.urls)
                embed.add_field(
                    name=f"URLs Tried ({len(state.urls)})",
                    value=url_list,
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Server Address",
                    value=f"`{state.urls[0]}`",
                    inline=False,
                )

            # Show last online time
            if state.last_online:
                embed.add_field(
                    name="Last Online",
                    value=f"<t:{int(state.last_online.timestamp())}:R>",
                    inline=True,
                )

        embed.set_footer(text="Minecraft Server Status")

        await channel.send(embed=embed)
        logger.info(f"Sent offline notification for {server_name}")

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def _format_duration(self, seconds: float) -> str:
        """
        Format a duration in seconds to a human-readable string.

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
        """
        seconds = int(seconds)

        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"

        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"

        hours = minutes // 60
        remaining_minutes = minutes % 60
        if hours < 24:
            if remaining_minutes:
                return f"{hours}h {remaining_minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"

        days = hours // 24
        remaining_hours = hours % 24
        if remaining_hours:
            return f"{days}d {remaining_hours}h"
        return f"{days} day{'s' if days != 1 else ''}"

    # -------------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------------

    @app_commands.command(
        name="mc-status",
        description="Check Minecraft server status",
    )
    async def status_command(self, interaction: discord.Interaction) -> None:
        """
        Display status of all configured Minecraft servers.

        Shows:
            - Online/offline status for each server
            - Player count and names (if available)
            - Server version and latency
            - Active URL being used

        This command is available to all users.
        """
        await interaction.response.defer()

        service = self.bot.minecraft_service
        servers = service.get_all_servers()

        if not servers:
            await interaction.followup.send(
                "ℹ️ No Minecraft servers configured.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🎮 Minecraft Server Status",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )

        all_online = True
        for state in servers:
            try:
                status = await service.get_status(state.name)

                # Build status text
                status_text = "✅ **Online**\n"
                status_text += f"Players: {status.player_count}/{status.max_players}\n"
                status_text += f"Version: {status.version}\n"
                status_text += f"Latency: {status.latency_ms:.0f}ms"

                if status.player_names and not status.players_hidden:
                    player_list = ", ".join(sorted(status.player_names))
                    if len(player_list) > 100:
                        player_list = player_list[:100] + "..."
                    status_text += f"\n\n**Online:** {player_list}"
                elif status.players_hidden and status.player_count > 0:
                    status_text += "\n\n*Player list hidden*"

                embed.add_field(
                    name=f"🟢 {state.name}",
                    value=status_text,
                    inline=False,
                )

            except MinecraftError as e:
                all_online = False
                error_msg = str(e)
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."

                status_text = f"❌ **Offline**\n{error_msg}"
                if state.last_online:
                    status_text += f"\n\nLast online: <t:{int(state.last_online.timestamp())}:R>"

                embed.add_field(
                    name=f"🔴 {state.name}",
                    value=status_text,
                    inline=False,
                )

        if not all_online:
            embed.color = discord.Color.orange()

        embed.set_footer(text="Minecraft Server Monitor")

        await interaction.followup.send(embed=embed)


# =============================================================================
# Cog Setup
# =============================================================================


async def setup(bot: "MonolithBot") -> None:
    """
    Setup function called by discord.py to load the cog.

    Args:
        bot: The MonolithBot instance to add the cog to.
    """
    await bot.add_cog(MinecraftHealthCog(bot))

"""
Minecraft player announcement cog for tracking player joins.

This cog monitors all configured Minecraft servers for player activity,
announcing when players join a server. It uses polling to detect player
changes by comparing current player lists to previous snapshots.

Key Features:
    - Periodic player list polling at configurable intervals
    - Multi-server support with independent tracking per server
    - Player join detection via set differencing
    - Rich Discord embeds for announcements
    - Graceful handling of servers with hidden player lists

Detection Method:
    The cog uses a polling-based approach for player detection:

    1. Periodically query each server's player list
    2. Compare current players to previously stored set
    3. New players (in current but not in previous) = joins
    4. Update stored set with current players

    This approach trades real-time accuracy for simplicity and
    reliability, with detection latency equal to the polling interval.

Configuration:
    Uses these settings from bot.config.minecraft.schedule:
        - player_check_interval_seconds: How often to poll (default: 30)

    And from bot.config.minecraft:
        - announcement_channel_id: Where to send join announcements
        - servers: List of servers to monitor

Example Announcements:
    - 📥 "Steve joined Survival" - When a player joins
    - 📥 "2 players joined Creative" - When multiple players join

Note:
    Servers that hide their player lists (players_hidden=True) are
    gracefully skipped for join announcements since individual
    players cannot be identified.

See Also:
    - bot.services.minecraft: The service used for status queries
    - bot.cogs.minecraft.health: Companion cog for health monitoring
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from bot.services.minecraft import MinecraftError, MinecraftServerStatus
from bot.services.scheduler import create_scheduler

if TYPE_CHECKING:
    from bot.main import MonolithBot

# Module logger
logger = logging.getLogger("monolithbot.minecraft.players")


class MinecraftPlayersCog(commands.Cog, name="MinecraftPlayers"):
    """
    Discord cog for announcing player joins on Minecraft servers.

    This cog polls all configured Minecraft servers at regular intervals
    to detect when new players join. When new players are detected,
    it sends announcements to the configured Discord channel.

    The cog relies on the MinecraftService for:
        - Querying server status (player lists)
        - Tracking previous player sets (for diff detection)
        - Multi-URL failover if a server has backup addresses

    Attributes:
        bot: Reference to the MonolithBot instance.
        scheduler: APScheduler instance for periodic polling.

    Note:
        This cog does NOT send notifications on startup to avoid
        flooding the channel with "X joined" messages when the bot
        reconnects.

    Example:
        The cog is automatically loaded by the bot. To manually interact:

        >>> players_cog = bot.get_cog("MinecraftPlayers")
    """

    def __init__(self, bot: "MonolithBot") -> None:
        """
        Initialize the player announcements cog.

        Args:
            bot: The MonolithBot instance. Used to access configuration,
                shared services, and Discord channels.
        """
        self.bot = bot
        self.scheduler = create_scheduler(bot.config)
        self._initialized = False

    # -------------------------------------------------------------------------
    # Cog Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Called automatically by discord.py when the cog is added to the bot.
        Performs initial player list snapshot for all servers (without
        announcements) and starts the periodic polling scheduler.
        """
        # Initialize player lists without announcing (avoid startup flood)
        await self._initialize_player_lists()
        self._initialized = True

        # Schedule periodic player checks
        interval_seconds = (
            self.bot.config.minecraft.schedule.player_check_interval_seconds
        )
        self.scheduler.add_job(
            self._run_player_checks,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id="minecraft_player_check",
            replace_existing=True,
        )

        self.scheduler.start()
        server_count = len(self.bot.minecraft_service.get_all_servers())
        logger.info(
            f"Minecraft player monitoring started for {server_count} server(s) "
            f"(checking every {interval_seconds} seconds)"
        )

    async def cog_unload(self) -> None:
        """
        Clean up resources when the cog is unloaded.

        Called automatically by discord.py when the cog is removed from the bot.
        Stops the scheduler.
        """
        self.scheduler.shutdown(wait=False)
        logger.info("Minecraft player monitoring cog unloaded")

    # -------------------------------------------------------------------------
    # Player Tracking Logic
    # -------------------------------------------------------------------------

    async def _initialize_player_lists(self) -> None:
        """
        Initialize player lists for all servers without sending announcements.

        This runs once at startup to capture the current player state.
        Any players currently online will NOT be announced - only players
        who join AFTER the bot starts will trigger announcements.
        """
        service = self.bot.minecraft_service

        for server_name in service.get_server_names():
            try:
                status = await service.get_status(server_name)

                # Update player tracking
                service.update_players(server_name, status.player_names)

                if status.players_hidden:
                    logger.info(
                        f"Initial player snapshot for {server_name}: "
                        f"{status.player_count} players (list hidden)"
                    )
                else:
                    player_list = ", ".join(status.player_names) or "none"
                    logger.info(
                        f"Initial player snapshot for {server_name}: "
                        f"{status.player_count} players ({player_list})"
                    )

            except MinecraftError as e:
                logger.warning(
                    f"Could not get initial player list for {server_name}: {e}"
                )
                # Initialize empty set - we'll detect joins when server comes online
                service.update_players(server_name, set())

    async def _run_player_checks(self) -> None:
        """
        Execute scheduled player checks for all configured servers.

        This is the main polling method called by the scheduler.
        It iterates through all servers, checking for player joins.
        """
        logger.debug("Running Minecraft player checks...")

        service = self.bot.minecraft_service

        for server_name in service.get_server_names():
            await self._check_server_players(server_name)

    async def _check_server_players(self, server_name: str) -> None:
        """
        Check a single server for player joins and announce new players.

        Args:
            server_name: Name of the server to check.
        """
        service = self.bot.minecraft_service
        state = service.get_server_state(server_name)

        if state is None:
            logger.error(f"Unknown server in player check: {server_name}")
            return

        # Skip if server is known to be offline
        if state.online is False:
            logger.debug(f"Skipping player check for offline server: {server_name}")
            return

        try:
            status = await service.get_status(server_name)
            await self._process_player_changes(server_name, status)

        except MinecraftError as e:
            logger.debug(f"Player check failed for {server_name}: {e}")
            # Don't update player list on failure - health cog handles offline

    async def _process_player_changes(
        self, server_name: str, status: MinecraftServerStatus
    ) -> None:
        """
        Process player changes and send join announcements.

        Args:
            server_name: Name of the server.
            status: Current status containing player information.
        """
        service = self.bot.minecraft_service

        # Handle servers with hidden player lists
        if status.players_hidden:
            logger.debug(
                f"Server {server_name} has hidden player list - "
                f"cannot detect individual joins"
            )
            return

        # Detect new players
        new_players = service.detect_player_joins(server_name, status.player_names)

        if new_players:
            logger.info(
                f"Detected {len(new_players)} new player(s) on {server_name}: "
                f"{', '.join(new_players)}"
            )
            await self._send_join_announcement(server_name, new_players, status)

    # -------------------------------------------------------------------------
    # Discord Announcements
    # -------------------------------------------------------------------------

    async def _send_join_announcement(
        self,
        server_name: str,
        new_players: set[str],
        status: MinecraftServerStatus,
    ) -> None:
        """
        Send a Discord announcement for player joins.

        Creates an embed announcing which players joined the server,
        with additional context like current player count.

        Args:
            server_name: Name of the server players joined.
            new_players: Set of player names who just joined.
            status: Current server status (for additional context).
        """
        channel = self.bot.get_channel(
            self.bot.config.minecraft.announcement_channel_id
        )
        if channel is None:
            logger.error("Minecraft announcement channel not found")
            return

        # Determine embed content based on player count
        player_count = len(new_players)
        player_list = sorted(new_players)

        if player_count == 1:
            # Single player join
            player_name = player_list[0]
            embed = discord.Embed(
                title=f"📥 {player_name} joined {server_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc),
            )
        else:
            # Multiple players joined
            embed = discord.Embed(
                title=f"📥 {player_count} players joined {server_name}",
                description=", ".join(player_list),
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc),
            )

        # Add server context
        embed.add_field(
            name="Online Now",
            value=f"{status.player_count}/{status.max_players}",
            inline=True,
        )

        # Show all online players if not too many
        if status.player_names and len(status.player_names) <= 10:
            all_players = ", ".join(sorted(status.player_names))
            embed.add_field(name="Players", value=all_players, inline=False)

        embed.set_footer(text=f"Minecraft • {server_name}")

        await channel.send(embed=embed)
        logger.debug(f"Sent join announcement for {player_count} player(s)")

    # -------------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------------

    @app_commands.command(
        name="mc-players",
        description="Show who's currently playing on Minecraft servers",
    )
    async def players_command(self, interaction: discord.Interaction) -> None:
        """
        Display current players on all Minecraft servers.

        Shows:
            - Player count for each server
            - List of online player names (if server allows)

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
            title="👥 Minecraft Players Online",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )

        total_players = 0
        for state in servers:
            try:
                status = await service.get_status(state.name)
                total_players += status.player_count

                if status.player_count == 0:
                    player_text = "*No players online*"
                elif status.players_hidden:
                    player_text = f"**{status.player_count}** player(s) online\n*Player list hidden by server*"
                elif status.player_names:
                    player_list = ", ".join(sorted(status.player_names))
                    if len(player_list) > 200:
                        player_list = player_list[:200] + "..."
                    player_text = (
                        f"**{status.player_count}** player(s) online\n{player_list}"
                    )
                else:
                    player_text = f"**{status.player_count}** player(s) online"

                embed.add_field(
                    name=f"🟢 {state.name}",
                    value=player_text,
                    inline=False,
                )

            except MinecraftError:
                embed.add_field(
                    name=f"🔴 {state.name}",
                    value="*Server offline*",
                    inline=False,
                )

        embed.description = f"**Total: {total_players}** player(s) across all servers"
        embed.set_footer(text="Minecraft Player Monitor")

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
    await bot.add_cog(MinecraftPlayersCog(bot))

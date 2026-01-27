"""
Health monitoring cog - Jellyfin server health checks.

This cog handles:
- Periodic health checks of the Jellyfin server
- Notifications when the server goes down or comes back online
- Tracking downtime duration
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from bot.services.jellyfin import (
    JellyfinClient,
    JellyfinConnectionError,
    JellyfinError,
    ServerInfo,
)
from bot.services.scheduler import create_scheduler

if TYPE_CHECKING:
    from bot.main import MonolithBot

logger = logging.getLogger("monolithbot.health")


class HealthCog(commands.Cog, name="Health"):
    """Cog for Jellyfin server health monitoring."""

    def __init__(self, bot: "MonolithBot"):
        self.bot = bot
        self.jellyfin: Optional[JellyfinClient] = None
        self.scheduler = create_scheduler(bot.config)

        self._server_online: Optional[bool] = None
        self._last_online: Optional[datetime] = None
        self._went_offline: Optional[datetime] = None
        self._last_server_info: Optional[ServerInfo] = None

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        self.jellyfin = JellyfinClient(
            base_url=self.bot.config.jellyfin.url,
            api_key=self.bot.config.jellyfin.api_key,
        )

        await self._initial_health_check()

        interval_minutes = self.bot.config.schedule.health_check_interval_minutes
        self.scheduler.add_job(
            self._run_health_check,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="health_check",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            f"Health monitoring started (checking every {interval_minutes} minutes)"
        )

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded."""
        self.scheduler.shutdown(wait=False)
        if self.jellyfin:
            await self.jellyfin.close()
        logger.info("Health monitoring cog unloaded")

    async def _initial_health_check(self) -> None:
        """Perform initial health check to establish baseline state."""
        try:
            self._last_server_info = await self.jellyfin.check_health()
            self._server_online = True
            self._last_online = datetime.now(timezone.utc)
            logger.info(
                f"Initial health check passed - "
                f"Server: {self._last_server_info.server_name} "
                f"v{self._last_server_info.version}"
            )
        except JellyfinError as e:
            self._server_online = False
            self._went_offline = datetime.now(timezone.utc)
            logger.warning(f"Initial health check failed: {e}")

    async def _run_health_check(self) -> None:
        """Execute a health check and handle state changes."""
        logger.debug("Running health check...")

        try:
            server_info = await self.jellyfin.check_health()
            self._last_server_info = server_info
            await self._handle_server_online(server_info)

        except JellyfinConnectionError as e:
            logger.warning(f"Health check failed - connection error: {e}")
            await self._handle_server_offline(str(e))

        except JellyfinError as e:
            logger.warning(f"Health check failed - API error: {e}")
            await self._handle_server_offline(str(e))

    async def _handle_server_online(self, server_info: ServerInfo) -> None:
        """Handle server being online."""
        was_offline = self._server_online is False

        self._server_online = True
        self._last_online = datetime.now(timezone.utc)

        if was_offline:
            downtime = None
            if self._went_offline:
                downtime = datetime.now(timezone.utc) - self._went_offline
                self._went_offline = None

            logger.info(
                f"Server came back online - {server_info.server_name} "
                f"v{server_info.version}"
            )
            await self._send_online_notification(server_info, downtime)

    async def _handle_server_offline(self, error_message: str) -> None:
        """Handle server being offline."""
        was_online = self._server_online is True or self._server_online is None

        if was_online:
            self._went_offline = datetime.now(timezone.utc)
            self._server_online = False
            logger.warning(f"Server went offline: {error_message}")
            await self._send_offline_notification(error_message)
        else:
            logger.debug("Server still offline")

    async def _send_online_notification(
        self,
        server_info: ServerInfo,
        downtime: Optional[datetime] = None,
    ) -> None:
        """Send notification that server is back online."""
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

    async def _send_offline_notification(self, error_message: str) -> None:
        """Send notification that server is offline."""
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

        embed.add_field(
            name="Error",
            value=f"```{error_message[:500]}```",
            inline=False,
        )

        embed.add_field(
            name="Server URL",
            value=self.bot.config.jellyfin.url,
            inline=False,
        )

        if self._last_online:
            embed.add_field(
                name="Last Online",
                value=f"<t:{int(self._last_online.timestamp())}:R>",
                inline=True,
            )

        embed.set_footer(text="Monolith Status")

        await channel.send(embed=embed)

    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to human-readable string."""
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


async def setup(bot: "MonolithBot") -> None:
    """Setup function for the cog."""
    await bot.add_cog(HealthCog(bot))

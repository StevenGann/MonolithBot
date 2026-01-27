"""
Announcements cog - Scheduled content announcements for Jellyfin.

This cog handles:
- Scheduled announcements of newly added content (Movies, TV Shows, Music)
- Rich Discord embeds with cover images and links
- Manual announcement triggering for admins
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands

from bot.services.jellyfin import JellyfinClient, JellyfinError, JellyfinItem
from bot.services.scheduler import create_scheduler, parse_time

if TYPE_CHECKING:
    from bot.main import MonolithBot

logger = logging.getLogger("monolithbot.announcements")

CONTENT_TYPE_COLORS = {
    "Movie": discord.Color.blue(),
    "Series": discord.Color.green(),
    "Audio": discord.Color.purple(),
    "Music": discord.Color.purple(),
    "Episode": discord.Color.teal(),
}

CONTENT_TYPE_EMOJI = {
    "Movie": "🎬",
    "Series": "📺",
    "Audio": "🎵",
    "Music": "🎵",
    "Episode": "📺",
}


class AnnouncementsCog(commands.Cog, name="Announcements"):
    """Cog for scheduled Jellyfin content announcements."""

    def __init__(self, bot: "MonolithBot"):
        self.bot = bot
        self.jellyfin: Optional[JellyfinClient] = None
        self.scheduler = create_scheduler(bot.config)
        self._last_announcement: Optional[datetime] = None

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        self.jellyfin = JellyfinClient(
            base_url=self.bot.config.jellyfin.url,
            api_key=self.bot.config.jellyfin.api_key,
        )

        self._schedule_announcements()
        self.scheduler.start()
        logger.info("Announcements cog loaded and scheduler started")

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded."""
        self.scheduler.shutdown(wait=False)
        if self.jellyfin:
            await self.jellyfin.close()
        logger.info("Announcements cog unloaded")

    def _schedule_announcements(self) -> None:
        """Schedule announcement jobs based on configuration."""
        for time_str in self.bot.config.schedule.announcement_times:
            try:
                hour, minute = parse_time(time_str)
                trigger = CronTrigger(hour=hour, minute=minute)

                self.scheduler.add_job(
                    self._run_announcement,
                    trigger=trigger,
                    id=f"announcement_{time_str}",
                    replace_existing=True,
                )

                logger.info(
                    f"Scheduled announcement at {time_str} "
                    f"({self.bot.config.schedule.timezone})"
                )

            except ValueError as e:
                logger.error(f"Invalid announcement time '{time_str}': {e}")

    async def _run_announcement(self) -> None:
        """Execute the scheduled announcement."""
        logger.info("Running scheduled announcement...")

        try:
            await self.announce_new_content()
        except Exception as e:
            logger.exception(f"Error during scheduled announcement: {e}")

    async def announce_new_content(self, channel: Optional[discord.TextChannel] = None) -> int:
        """
        Announce newly added content to Discord.

        Args:
            channel: Channel to send to (uses configured channel if None)

        Returns:
            Number of items announced
        """
        if channel is None:
            channel = self.bot.get_channel(self.bot.config.discord.announcement_channel_id)

        if channel is None:
            logger.error("Announcement channel not found")
            return 0

        if self.jellyfin is None:
            logger.error("Jellyfin client not initialized")
            return 0

        try:
            items_by_type = await self.jellyfin.get_all_recent_items(
                content_types=self.bot.config.content_types,
                hours=self.bot.config.schedule.lookback_hours,
            )
        except JellyfinError as e:
            logger.error(f"Failed to fetch items from Jellyfin: {e}")
            return 0

        if not items_by_type:
            logger.info("No new content to announce")
            return 0

        total_items = sum(len(items) for items in items_by_type.values())
        logger.info(f"Announcing {total_items} new items")

        header_embed = discord.Embed(
            title="🆕 New Content on Monolith",
            description=f"Here's what's been added in the last {self.bot.config.schedule.lookback_hours} hours!",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        await channel.send(embed=header_embed)

        for content_type, items in items_by_type.items():
            if not items:
                continue

            emoji = CONTENT_TYPE_EMOJI.get(content_type, "📦")
            type_name = self._get_type_display_name(content_type)

            section_embed = discord.Embed(
                title=f"{emoji} New {type_name}",
                color=CONTENT_TYPE_COLORS.get(content_type, discord.Color.greyple()),
            )
            await channel.send(embed=section_embed)

            for item in items[:10]:
                embed = self._create_item_embed(item)
                await channel.send(embed=embed)

            if len(items) > 10:
                overflow_embed = discord.Embed(
                    description=f"*...and {len(items) - 10} more {type_name.lower()}*",
                    color=discord.Color.greyple(),
                )
                await channel.send(embed=overflow_embed)

        self._last_announcement = datetime.now(timezone.utc)
        return total_items

    def _create_item_embed(self, item: JellyfinItem) -> discord.Embed:
        """Create a Discord embed for a Jellyfin item."""
        color = CONTENT_TYPE_COLORS.get(item.item_type, discord.Color.greyple())

        embed = discord.Embed(
            title=item.display_title,
            url=self.jellyfin.get_item_url(item.id),
            color=color,
        )

        if item.overview:
            description = item.overview[:300]
            if len(item.overview) > 300:
                description += "..."
            embed.description = description

        image_url = self.jellyfin.get_item_image_url(item.id)
        embed.set_thumbnail(url=image_url)

        if item.item_type == "Episode" and item.series_name:
            embed.add_field(name="Series", value=item.series_name, inline=True)

        if item.item_type == "Audio":
            if item.artists:
                embed.add_field(name="Artist", value=", ".join(item.artists), inline=True)
            if item.album:
                embed.add_field(name="Album", value=item.album, inline=True)

        if item.year:
            embed.add_field(name="Year", value=str(item.year), inline=True)

        return embed

    def _get_type_display_name(self, content_type: str) -> str:
        """Get human-readable name for content type."""
        names = {
            "Movie": "Movies",
            "Series": "TV Shows",
            "Audio": "Music",
            "Music": "Music",
            "Episode": "Episodes",
        }
        return names.get(content_type, content_type)

    @app_commands.command(name="announce", description="Manually trigger a content announcement")
    @app_commands.default_permissions(administrator=True)
    async def announce_command(self, interaction: discord.Interaction) -> None:
        """Manually trigger a content announcement (admin only)."""
        await interaction.response.defer(ephemeral=True)

        count = await self.announce_new_content()

        if count > 0:
            await interaction.followup.send(
                f"✅ Announced {count} new item(s)!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "ℹ️ No new content to announce.",
                ephemeral=True,
            )

    @app_commands.command(name="status", description="Check bot and Jellyfin status")
    async def status_command(self, interaction: discord.Interaction) -> None:
        """Check bot and Jellyfin server status."""
        await interaction.response.defer()

        embed = discord.Embed(
            title="MonolithBot Status",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Bot",
            value=f"✅ Online\nLatency: {round(self.bot.latency * 1000)}ms",
            inline=True,
        )

        try:
            server_info = await self.jellyfin.check_health()
            jellyfin_status = (
                f"✅ Online\n"
                f"Server: {server_info.server_name}\n"
                f"Version: {server_info.version}"
            )
        except JellyfinError as e:
            jellyfin_status = f"❌ Offline\nError: {e}"

        embed.add_field(name="Jellyfin", value=jellyfin_status, inline=True)

        next_run = None
        for job in self.scheduler.get_jobs():
            if job.id.startswith("announcement_"):
                if next_run is None or job.next_run_time < next_run:
                    next_run = job.next_run_time

        if next_run:
            embed.add_field(
                name="Next Announcement",
                value=f"<t:{int(next_run.timestamp())}:R>",
                inline=False,
            )

        if self._last_announcement:
            embed.add_field(
                name="Last Announcement",
                value=f"<t:{int(self._last_announcement.timestamp())}:R>",
                inline=False,
            )

        await interaction.followup.send(embed=embed)


async def setup(bot: "MonolithBot") -> None:
    """Setup function for the cog."""
    await bot.add_cog(AnnouncementsCog(bot))

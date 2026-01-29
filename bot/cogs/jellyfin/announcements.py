"""
Jellyfin announcements cog for scheduled content notifications.

This cog handles automatic announcements of newly added media content
to a Discord channel at configured times. It's the primary way users
stay informed about new movies, TV shows, and music on the server.

Key Features:
    - Scheduled announcements at configurable times (cron-based)
    - Support for multiple announcement times per day
    - Rich Discord embeds with cover art and direct links
    - Content grouped by type (Movies, TV Shows, Music)
    - Manual announcement trigger for administrators
    - Status command showing bot health and next announcement

Announcement Structure:
    When triggered, announcements are formatted as:

    ```
    ┌─────────────────────────────────────┐
    │ 🆕 New Content on Monolith          │  ← Header embed
    │ Here's what's been added...         │
    └─────────────────────────────────────┘

    ┌─────────────────────────────────────┐
    │ 🎬 New Movies                       │  ← Section header
    └─────────────────────────────────────┘

    ┌─────────────────────────────────────┐
    │ [Thumbnail] The Matrix (1999)       │  ← Item embed
    │             Plot description...      │     (up to 10 per type)
    │             Year: 1999              │
    └─────────────────────────────────────┘

    ... more items ...

    ┌─────────────────────────────────────┐
    │ 📺 New TV Shows                     │  ← Next section
    └─────────────────────────────────────┘

    ... etc ...
    ```

Slash Commands:
    /announce - Manually trigger an announcement (admin only)
    /status   - Show bot status, Jellyfin status, and schedule info

Configuration:
    Uses these settings from bot.config:
        - jellyfin.schedule.announcement_times: List of times like ["17:00", "21:00"]
        - jellyfin.schedule.timezone: IANA timezone for interpreting times
        - jellyfin.schedule.lookback_hours: How far back to look for "new" content
        - jellyfin.content_types: Which types to announce ["Movie", "Series", "Audio"]
        - discord.announcement_channel_id: Where to post announcements

See Also:
    - bot.services.jellyfin: API client for fetching content
    - bot.services.scheduler: Scheduler factory and time parsing
    - bot.cogs.jellyfin.health: Companion cog for server health monitoring
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

# Module logger
logger = logging.getLogger("monolithbot.jellyfin.announcements")


# =============================================================================
# Constants
# =============================================================================

# Color scheme for different content types in Discord embeds
CONTENT_TYPE_COLORS: dict[str, discord.Color] = {
    "Movie": discord.Color.blue(),
    "Series": discord.Color.green(),
    "Audio": discord.Color.purple(),
    "Music": discord.Color.purple(),  # Alias for Audio
    "Episode": discord.Color.teal(),
}

# Emoji prefixes for content type headers
CONTENT_TYPE_EMOJI: dict[str, str] = {
    "Movie": "🎬",
    "Series": "📺",
    "Audio": "🎵",
    "Music": "🎵",  # Alias for Audio
    "Episode": "📺",
}

# Maximum length for item descriptions (overview/plot)
MAX_DESCRIPTION_LENGTH = 300


class JellyfinAnnouncementsCog(commands.Cog, name="JellyfinAnnouncements"):
    """
    Discord cog for scheduled Jellyfin content announcements.

    This cog queries the Jellyfin server for recently added content
    and posts formatted announcements to Discord at configured times.

    Attributes:
        bot: Reference to the MonolithBot instance.
        jellyfin: Jellyfin API client for fetching content.
        scheduler: APScheduler instance for timed announcements.

    Example:
        The cog is automatically loaded. Commands available:

        >>> /status    # Check bot and server status
        >>> /announce  # Manually trigger announcement (admin only)
    """

    def __init__(self, bot: "MonolithBot") -> None:
        """
        Initialize the announcements cog.

        Args:
            bot: The MonolithBot instance. Used to access configuration
                and Discord channels.
        """
        self.bot = bot
        self.jellyfin: Optional[JellyfinClient] = None
        self.scheduler = create_scheduler(bot.config)

        # Track when the last announcement was sent
        self._last_announcement: Optional[datetime] = None

    # -------------------------------------------------------------------------
    # Cog Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Called automatically by discord.py when the cog is added to the bot.
        Sets up the Jellyfin client, schedules announcement jobs for each
        configured time, and starts the scheduler.
        """
        # Initialize Jellyfin client
        self.jellyfin = JellyfinClient(
            base_url=self.bot.config.jellyfin.url,
            api_key=self.bot.config.jellyfin.api_key,
        )

        # Schedule announcements for each configured time
        self._schedule_announcements()
        self.scheduler.start()
        logger.info("Jellyfin announcements cog loaded and scheduler started")

    async def cog_unload(self) -> None:
        """
        Clean up resources when the cog is unloaded.

        Called automatically by discord.py when the cog is removed.
        Stops the scheduler and closes the HTTP client session.
        """
        self.scheduler.shutdown(wait=False)
        if self.jellyfin:
            await self.jellyfin.close()
        logger.info("Jellyfin announcements cog unloaded")

    # -------------------------------------------------------------------------
    # Scheduling
    # -------------------------------------------------------------------------

    def _schedule_announcements(self) -> None:
        """
        Schedule announcement jobs based on configuration.

        Creates a cron-triggered job for each time in the
        `config.jellyfin.schedule.announcement_times` list. Invalid times
        are logged and skipped.
        """
        for time_str in self.bot.config.jellyfin.schedule.announcement_times:
            try:
                hour, minute = parse_time(time_str)
                trigger = CronTrigger(hour=hour, minute=minute)

                self.scheduler.add_job(
                    self._run_announcement,
                    trigger=trigger,
                    id=f"jellyfin_announcement_{time_str}",
                    replace_existing=True,
                )

                logger.info(
                    f"Scheduled Jellyfin announcement at {time_str} "
                    f"({self.bot.config.jellyfin.schedule.timezone})"
                )

            except ValueError as e:
                logger.error(f"Invalid announcement time '{time_str}': {e}")

    async def _run_announcement(self) -> None:
        """
        Execute a scheduled announcement.

        This is the callback invoked by APScheduler at each configured time.
        Wraps `announce_new_content()` with exception handling to prevent
        scheduler job failures from stopping future executions.
        """
        logger.info("Running scheduled Jellyfin announcement...")

        try:
            count = await self.announce_new_content()
            logger.info(f"Scheduled announcement complete: {count} items announced")
        except Exception as e:
            # Log but don't raise - we don't want to break the scheduler
            logger.exception(f"Error during scheduled announcement: {e}")

    # -------------------------------------------------------------------------
    # Announcement Logic
    # -------------------------------------------------------------------------

    async def announce_new_content(
        self,
        channel: Optional[discord.TextChannel] = None,
    ) -> int:
        """
        Announce newly added content to Discord.

        Fetches recently added items from Jellyfin, groups them by type,
        and sends formatted embeds to the announcement channel.

        Args:
            channel: Discord channel to send announcements to.
                If None, uses the configured announcement channel.

        Returns:
            Total number of items announced. Returns 0 if there's no
            new content or if an error occurs.

        Note:
            This method can be called directly for testing or by the
            `/announce` command for manual triggering.
        """
        # Resolve the target channel
        if channel is None:
            channel = self.bot.get_channel(
                self.bot.config.discord.announcement_channel_id
            )

        if channel is None:
            logger.error("Announcement channel not found")
            return 0

        if self.jellyfin is None:
            logger.error("Jellyfin client not initialized")
            return 0

        # Fetch recent items from Jellyfin
        try:
            items_by_type = await self.jellyfin.get_all_recent_items(
                content_types=self.bot.config.jellyfin.content_types,
                hours=self.bot.config.jellyfin.schedule.lookback_hours,
            )
        except JellyfinError as e:
            logger.error(f"Failed to fetch items from Jellyfin: {e}")
            return 0

        # Nothing to announce?
        if not items_by_type:
            logger.info("No new content to announce")
            return 0

        # Calculate total for logging and return value
        total_items = sum(len(items) for items in items_by_type.values())
        logger.info(f"Announcing {total_items} new items")

        # Send header embed
        header_embed = discord.Embed(
            title="🆕 New Content on Monolith",
            description=(
                f"Here's what's been added in the last "
                f"{self.bot.config.jellyfin.schedule.lookback_hours} hours!"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        await channel.send(embed=header_embed)

        # Send each content type section
        for content_type, items in items_by_type.items():
            if not items:
                continue

            await self._send_content_section(channel, content_type, items)

        # Update tracking
        self._last_announcement = datetime.now(timezone.utc)
        return total_items

    async def _send_content_section(
        self,
        channel: discord.TextChannel,
        content_type: str,
        items: list[JellyfinItem],
    ) -> None:
        """
        Send a section of announcements for a single content type.

        Sends a section header followed by individual item embeds.
        Limits to config.jellyfin.schedule.max_items_per_type items with an overflow message.

        Args:
            channel: Discord channel to send to.
            content_type: Type of content (e.g., "Movie", "Series").
            items: List of JellyfinItem objects to announce.
        """
        # Get display formatting for this content type
        emoji = CONTENT_TYPE_EMOJI.get(content_type, "📦")
        type_name = self._get_type_display_name(content_type)
        color = CONTENT_TYPE_COLORS.get(content_type, discord.Color.greyple())

        # Get max items from config
        max_items = self.bot.config.jellyfin.schedule.max_items_per_type

        # Send section header with link to Recently Added page
        recently_added_url = self.jellyfin.get_recently_added_url(content_type)
        section_embed = discord.Embed(
            title=f"{emoji} New {type_name}",
            url=recently_added_url,
            color=color,
        )
        await channel.send(embed=section_embed)

        # Send individual item embeds (limited)
        for item in items[:max_items]:
            embed = self._create_item_embed(item)
            await channel.send(embed=embed)

        # Show overflow message if there are more items
        if len(items) > max_items:
            overflow_count = len(items) - max_items
            overflow_embed = discord.Embed(
                description=f"*...and {overflow_count} more {type_name.lower()}*",
                color=discord.Color.greyple(),
            )
            await channel.send(embed=overflow_embed)

    # -------------------------------------------------------------------------
    # Embed Builders
    # -------------------------------------------------------------------------

    def _create_item_embed(self, item: JellyfinItem) -> discord.Embed:
        """
        Create a Discord embed for a single Jellyfin item.

        Builds a rich embed with the item's title, description, thumbnail,
        and metadata fields appropriate for its type.

        Args:
            item: The JellyfinItem to create an embed for.

        Returns:
            Configured discord.Embed ready to send.
        """
        color = CONTENT_TYPE_COLORS.get(item.item_type, discord.Color.greyple())

        # Create base embed with title linking to Jellyfin
        embed = discord.Embed(
            title=item.display_title,
            url=self.jellyfin.get_item_url(item.id),
            color=color,
        )

        # Add truncated description/overview if available
        if item.overview:
            description = item.overview[:MAX_DESCRIPTION_LENGTH]
            if len(item.overview) > MAX_DESCRIPTION_LENGTH:
                description += "..."
            embed.description = description

        # Add cover art thumbnail
        image_url = self.jellyfin.get_item_image_url(item.id)
        embed.set_thumbnail(url=image_url)

        # Add type-specific fields
        self._add_item_fields(embed, item)

        return embed

    def _add_item_fields(self, embed: discord.Embed, item: JellyfinItem) -> None:
        """
        Add metadata fields to an item embed based on content type.

        Different content types have different relevant metadata:
            - Episodes: Series name
            - Audio: Artist(s), Album
            - All types: Year (if available)
            - Test mode: Date added to library (for validating time filtering)

        Args:
            embed: The embed to add fields to (modified in place).
            item: The JellyfinItem to extract metadata from.
        """
        # Episode-specific: show series name
        if item.item_type == "Episode" and item.series_name:
            embed.add_field(name="Series", value=item.series_name, inline=True)

        # Audio-specific: show artist and album
        if item.item_type == "Audio":
            if item.artists:
                embed.add_field(
                    name="Artist",
                    value=", ".join(item.artists),
                    inline=True,
                )
            if item.album:
                embed.add_field(name="Album", value=item.album, inline=True)

        # Universal: show year if available
        if item.year:
            embed.add_field(name="Year", value=str(item.year), inline=True)

        # Test mode: show date added to help validate time filtering
        if self.bot.test_mode and item.date_created:
            embed.add_field(
                name="Added to Library",
                value=f"<t:{int(item.date_created.timestamp())}:F>",
                inline=False,
            )

    # -------------------------------------------------------------------------
    # Display Helpers
    # -------------------------------------------------------------------------

    def _get_type_display_name(self, content_type: str) -> str:
        """
        Get a human-readable plural name for a content type.

        Args:
            content_type: Internal content type string.

        Returns:
            User-friendly display name (plural form).

        Examples:
            >>> self._get_type_display_name("Movie")
            'Movies'
            >>> self._get_type_display_name("Series")
            'TV Shows'
        """
        names = {
            "Movie": "Movies",
            "Series": "TV Shows",
            "Audio": "Music",
            "Music": "Music",
            "Episode": "Episodes",
        }
        return names.get(content_type, content_type)

    # -------------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------------

    @app_commands.command(
        name="announce",
        description="Manually trigger a content announcement",
    )
    @app_commands.default_permissions(administrator=True)
    async def announce_command(self, interaction: discord.Interaction) -> None:
        """
        Manually trigger a content announcement (admin only).

        This slash command allows administrators to trigger an announcement
        immediately without waiting for the scheduled time. Useful for
        testing or after adding a batch of new content.

        The response is ephemeral (only visible to the admin).
        """
        # Defer since fetching from Jellyfin may take a moment
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

    @app_commands.command(
        name="status",
        description="Check bot and Jellyfin status",
    )
    async def status_command(self, interaction: discord.Interaction) -> None:
        """
        Display bot and Jellyfin server status.

        Shows:
            - Bot online status and latency
            - Jellyfin server status (online/offline with details)
            - Next scheduled announcement time
            - Last announcement time (if any)

        This command is available to all users.
        """
        await interaction.response.defer()

        embed = discord.Embed(
            title="MonolithBot Status",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )

        # Bot status
        embed.add_field(
            name="Bot",
            value=f"✅ Online\nLatency: {round(self.bot.latency * 1000)}ms",
            inline=True,
        )

        # Jellyfin status
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

        # Find next scheduled announcement
        next_run = None
        for job in self.scheduler.get_jobs():
            if job.id.startswith("jellyfin_announcement_"):
                if next_run is None or job.next_run_time < next_run:
                    next_run = job.next_run_time

        if next_run:
            # Use Discord's relative timestamp format
            embed.add_field(
                name="Next Announcement",
                value=f"<t:{int(next_run.timestamp())}:R>",
                inline=False,
            )

        # Show last announcement time if we've announced anything
        if self._last_announcement:
            embed.add_field(
                name="Last Announcement",
                value=f"<t:{int(self._last_announcement.timestamp())}:R>",
                inline=False,
            )

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
    await bot.add_cog(JellyfinAnnouncementsCog(bot))

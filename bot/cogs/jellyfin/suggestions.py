"""
Jellyfin suggestions cog for random content recommendations.

This cog handles automatic posting of random content suggestions
to a Discord channel at configured times. It helps users discover
content they might not have otherwise found in their library.

Key Features:
    - Scheduled suggestions at configurable times (cron-based)
    - Random selection of movies, TV shows, and music albums
    - Rich Discord embeds with cover art and direct links
    - Manual suggestion trigger via slash command

Suggestion Structure:
    When triggered, suggestions are formatted as:

    ```
    ┌─────────────────────────────────────────┐
    │ 🎲 Random Suggestions                   │  ← Header embed
    │ Here are some random picks from the     │
    │ library you might enjoy!                │
    └─────────────────────────────────────────┘

    ┌─────────────────────────────────────────┐
    │ [Thumbnail] 🎬 Movie Suggestion         │  ← Movie embed
    │             The Matrix (1999)           │
    │             Plot description...         │
    └─────────────────────────────────────────┘

    ┌─────────────────────────────────────────┐
    │ [Thumbnail] 📺 TV Show Suggestion       │  ← Series embed
    │             Breaking Bad (2008)         │
    │             Plot description...         │
    └─────────────────────────────────────────┘

    ┌─────────────────────────────────────────┐
    │ [Thumbnail] 🎵 Album Suggestion         │  ← Album embed
    │             Artist - Album Name         │
    └─────────────────────────────────────────┘
    ```

Slash Commands:
    /suggest - Get random suggestions for all types (movie, show, album)
    /suggest movie - Get a random movie suggestion
    /suggest show - Get a random TV show suggestion
    /suggest episode - Get a random episode suggestion
    /suggest album - Get a random album suggestion
    /suggest song - Get a random song suggestion

Configuration:
    Uses these settings from bot.config:
        - jellyfin.schedule.suggestion_times: List of times like ["12:00", "20:00"]
        - jellyfin.schedule.timezone: IANA timezone for interpreting times
        - discord.announcement_channel_id: Where to post suggestions

See Also:
    - bot.services.jellyfin: API client for fetching content
    - bot.services.scheduler: Scheduler factory and time parsing
    - bot.cogs.jellyfin.announcements: Similar cog for new content announcements
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
logger = logging.getLogger("monolithbot.jellyfin.suggestions")


# =============================================================================
# Constants
# =============================================================================

# Content types for scheduled suggestions (Movie, Series, and MusicAlbum)
SUGGESTION_TYPES = ["Movie", "Series", "MusicAlbum"]

# Mapping from user-friendly command choices to Jellyfin types
CONTENT_TYPE_CHOICES = {
    "movie": "Movie",
    "show": "Series",
    "episode": "Episode",
    "album": "MusicAlbum",
    "song": "Audio",
}

# Display names and emojis for each suggestion type
SUGGESTION_CONFIG = {
    "Movie": {
        "emoji": "🎬",
        "title": "Movie Suggestion",
        "color": discord.Color.blue(),
    },
    "Series": {
        "emoji": "📺",
        "title": "TV Show Suggestion",
        "color": discord.Color.green(),
    },
    "Episode": {
        "emoji": "📺",
        "title": "Episode Suggestion",
        "color": discord.Color.teal(),
    },
    "MusicAlbum": {
        "emoji": "💿",
        "title": "Album Suggestion",
        "color": discord.Color.purple(),
    },
    "Audio": {
        "emoji": "🎵",
        "title": "Song Suggestion",
        "color": discord.Color.purple(),
    },
}

# Maximum length for item descriptions
MAX_DESCRIPTION_LENGTH = 300


class JellyfinSuggestionsCog(commands.Cog, name="JellyfinSuggestions"):
    """
    Discord cog for random Jellyfin content suggestions.

    This cog queries the Jellyfin server for random content
    and posts suggestions to Discord at configured times.

    Attributes:
        bot: Reference to the MonolithBot instance.
        jellyfin: Jellyfin API client for fetching content.
        scheduler: APScheduler instance for timed suggestions.

    Example:
        The cog is automatically loaded. Commands available:

        >>> /suggest  # Get random suggestions
    """

    def __init__(self, bot: "MonolithBot") -> None:
        """
        Initialize the suggestions cog.

        Args:
            bot: The MonolithBot instance. Used to access configuration
                and Discord channels.
        """
        self.bot = bot
        self.jellyfin: Optional[JellyfinClient] = None
        self.scheduler = create_scheduler(bot.config)

        # Track when the last suggestion was posted
        self._last_suggestion: Optional[datetime] = None

    # -------------------------------------------------------------------------
    # Cog Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Called automatically by discord.py when the cog is added to the bot.
        Sets up the Jellyfin client, schedules suggestion jobs for each
        configured time, and starts the scheduler.
        """
        # Initialize Jellyfin client
        self.jellyfin = JellyfinClient(
            base_url=self.bot.config.jellyfin.url,
            api_key=self.bot.config.jellyfin.api_key,
        )

        # Schedule suggestions for each configured time
        self._schedule_suggestions()
        self.scheduler.start()
        logger.info("Jellyfin suggestions cog loaded and scheduler started")

    async def cog_unload(self) -> None:
        """
        Clean up resources when the cog is unloaded.

        Called automatically by discord.py when the cog is removed.
        Stops the scheduler and closes the HTTP client session.
        """
        self.scheduler.shutdown(wait=False)
        if self.jellyfin:
            await self.jellyfin.close()
        logger.info("Jellyfin suggestions cog unloaded")

    # -------------------------------------------------------------------------
    # Scheduling
    # -------------------------------------------------------------------------

    def _schedule_suggestions(self) -> None:
        """
        Schedule suggestion jobs based on configuration.

        Creates a cron-triggered job for each time in the
        `config.jellyfin.schedule.suggestion_times` list. Invalid times
        are logged and skipped.
        """
        for time_str in self.bot.config.jellyfin.schedule.suggestion_times:
            try:
                hour, minute = parse_time(time_str)
                trigger = CronTrigger(hour=hour, minute=minute)

                self.scheduler.add_job(
                    self._run_suggestion,
                    trigger=trigger,
                    id=f"jellyfin_suggestion_{time_str}",
                    replace_existing=True,
                )

                logger.info(
                    f"Scheduled Jellyfin suggestion at {time_str} "
                    f"({self.bot.config.jellyfin.schedule.timezone})"
                )

            except ValueError as e:
                logger.error(f"Invalid suggestion time '{time_str}': {e}")

    async def _run_suggestion(self) -> None:
        """
        Execute a scheduled suggestion.

        This is the callback invoked by APScheduler at each configured time.
        Wraps `post_random_suggestions()` with exception handling to prevent
        scheduler job failures from stopping future executions.
        """
        logger.info("Running scheduled Jellyfin suggestion...")

        try:
            count = await self.post_random_suggestions()
            logger.info(f"Scheduled suggestion complete: {count} items suggested")
        except Exception as e:
            # Log but don't raise - we don't want to break the scheduler
            logger.exception(f"Error during scheduled suggestion: {e}")

    # -------------------------------------------------------------------------
    # Suggestion Logic
    # -------------------------------------------------------------------------

    async def post_random_suggestions(
        self,
        channel: Optional[discord.TextChannel] = None,
    ) -> int:
        """
        Post random content suggestions to Discord.

        Fetches random items from Jellyfin (one movie, one TV show,
        one music album) and sends formatted embeds to the channel.

        Args:
            channel: Discord channel to send suggestions to.
                If None, uses the configured announcement channel.

        Returns:
            Total number of items suggested. Returns 0 if there's no
            content or if an error occurs.

        Note:
            This method can be called directly for testing or by the
            `/suggest` command for manual triggering.
        """
        # Resolve the target channel
        if channel is None:
            channel = self.bot.get_channel(
                self.bot.config.discord.announcement_channel_id
            )

        if channel is None:
            logger.error("Suggestion channel not found")
            return 0

        if self.jellyfin is None:
            logger.error("Jellyfin client not initialized")
            return 0

        # Fetch random items from Jellyfin
        try:
            suggestions = await self.jellyfin.get_random_items_by_type(SUGGESTION_TYPES)
        except JellyfinError as e:
            logger.error(f"Failed to fetch suggestions from Jellyfin: {e}")
            return 0

        # Nothing to suggest?
        if not suggestions:
            logger.info("No content available for suggestions")
            return 0

        # Send header embed
        header_embed = discord.Embed(
            title="🎲 Random Suggestions",
            description="Here are some random picks from the library you might enjoy!",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        await channel.send(embed=header_embed)

        # Send each suggestion
        for content_type in SUGGESTION_TYPES:
            if content_type in suggestions:
                item = suggestions[content_type]
                embed = self._create_suggestion_embed(content_type, item)
                await channel.send(embed=embed)

        # Update tracking
        self._last_suggestion = datetime.now(timezone.utc)
        return len(suggestions)

    # -------------------------------------------------------------------------
    # Embed Builders
    # -------------------------------------------------------------------------

    def _create_suggestion_embed(
        self, content_type: str, item: JellyfinItem
    ) -> discord.Embed:
        """
        Create a Discord embed for a suggestion item.

        Builds a rich embed with the item's title, description, thumbnail,
        and metadata fields appropriate for its type.

        Args:
            content_type: The type of content (Movie, Series, MusicAlbum).
            item: The JellyfinItem to create an embed for.

        Returns:
            Configured discord.Embed ready to send.
        """
        config = SUGGESTION_CONFIG.get(
            content_type,
            {"emoji": "📦", "title": "Suggestion", "color": discord.Color.greyple()},
        )

        # Create base embed with title linking to Jellyfin
        embed = discord.Embed(
            title=f"{config['emoji']} {config['title']}",
            url=self.jellyfin.get_item_url(item.id),
            color=config["color"],
        )

        # Add item name as a field or in description
        embed.add_field(name="Title", value=item.display_title, inline=False)

        # Add truncated description/overview if available
        if item.overview:
            description = item.overview[:MAX_DESCRIPTION_LENGTH]
            if len(item.overview) > MAX_DESCRIPTION_LENGTH:
                description += "..."
            embed.add_field(name="Overview", value=description, inline=False)

        # Add cover art thumbnail
        image_url = self.jellyfin.get_item_image_url(item.id)
        embed.set_thumbnail(url=image_url)

        # Add type-specific fields
        self._add_item_fields(embed, item)

        return embed

    def _add_item_fields(self, embed: discord.Embed, item: JellyfinItem) -> None:
        """
        Add metadata fields to a suggestion embed based on content type.

        Different content types have different relevant metadata:
            - MusicAlbum: Artist(s)
            - All types: Year (if available)

        Args:
            embed: The embed to add fields to (modified in place).
            item: The JellyfinItem to extract metadata from.
        """
        # Audio/Album-specific: show artist
        if item.item_type in ("Audio", "MusicAlbum") and item.artists:
            embed.add_field(
                name="Artist",
                value=", ".join(item.artists),
                inline=True,
            )

        # Show year if available
        if item.year:
            embed.add_field(name="Year", value=str(item.year), inline=True)

    # -------------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------------

    @app_commands.command(
        name="suggest",
        description="Get a random content suggestion from the library",
    )
    @app_commands.describe(
        content_type="Type of content to suggest (leave empty for all types)"
    )
    @app_commands.choices(
        content_type=[
            app_commands.Choice(name="Movie", value="movie"),
            app_commands.Choice(name="TV Show", value="show"),
            app_commands.Choice(name="Episode", value="episode"),
            app_commands.Choice(name="Album", value="album"),
            app_commands.Choice(name="Song", value="song"),
        ]
    )
    async def suggest_command(
        self,
        interaction: discord.Interaction,
        content_type: Optional[str] = None,
    ) -> None:
        """
        Get a random suggestion from the library.

        If no content type is specified, posts suggestions for all types
        (movie, show, album). If a specific type is given, posts just
        one suggestion of that type.

        Available to all users.
        """
        # Defer since fetching from Jellyfin may take a moment
        await interaction.response.defer()

        if self.jellyfin is None:
            await interaction.followup.send(
                "❌ Jellyfin client not initialized.",
                ephemeral=True,
            )
            return

        # If no content type specified, post all suggestions
        if content_type is None:
            count = await self.post_random_suggestions(interaction.channel)
            if count > 0:
                await interaction.followup.send(
                    f"✅ Posted {count} random suggestion(s)!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "ℹ️ No content available for suggestions.",
                    ephemeral=True,
                )
            return

        # Get the Jellyfin type from the user's choice
        jellyfin_type = CONTENT_TYPE_CHOICES.get(content_type)
        if not jellyfin_type:
            await interaction.followup.send(
                f"❌ Unknown content type: {content_type}",
                ephemeral=True,
            )
            return

        # Fetch a random item of the specified type
        try:
            item = await self.jellyfin.get_random_item(jellyfin_type)
        except JellyfinError as e:
            await interaction.followup.send(
                f"❌ Failed to fetch from Jellyfin: {e}",
                ephemeral=True,
            )
            return

        if item is None:
            await interaction.followup.send(
                f"ℹ️ No {content_type} content available in the library.",
            )
            return

        # Create and send the suggestion embed
        embed = self._create_suggestion_embed(jellyfin_type, item)
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
    await bot.add_cog(JellyfinSuggestionsCog(bot))

"""
MonolithBot - Discord bot for Jellyfin server monitoring and announcements.

This module serves as the entry point for MonolithBot, handling:
- Command-line argument parsing
- Logging configuration
- Bot initialization and lifecycle management
- Graceful shutdown on SIGINT/SIGTERM

Usage:
    python -m bot.main                    # Run with default config.json
    python -m bot.main --config my.json   # Run with custom config file
    python -m bot.main --verbose          # Run with debug logging

See Also:
    - bot.config: Configuration loading and validation
    - bot.cogs.announcements: Scheduled content announcements
    - bot.cogs.health: Server health monitoring
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import NoReturn

import discord
from discord.ext import commands

from bot.config import Config, ConfigurationError, load_config

# Module-level logger for MonolithBot core
logger = logging.getLogger("monolithbot")


class MonolithBot(commands.Bot):
    """
    Main Discord bot class for MonolithBot.

    Extends discord.py's Bot class with Jellyfin monitoring capabilities.
    Configuration is stored on the instance and accessible to all cogs
    via `self.bot.config`.

    Attributes:
        config: The loaded configuration object containing Discord,
            Jellyfin, and scheduling settings.
        test_mode: If True, run health check and announcement once on startup.

    Example:
        >>> config = load_config(Path("config.json"))
        >>> bot = MonolithBot(config)
        >>> await bot.start(config.discord.token)
    """

    def __init__(self, config: Config, test_mode: bool = False) -> None:
        """
        Initialize the MonolithBot instance.

        Args:
            config: Validated configuration object containing all settings
                required for bot operation (Discord token, Jellyfin URL, etc.)
            test_mode: If True, run health check and announcement once on startup.
        """
        # Configure Discord intents
        # We only need default intents for slash commands and sending messages
        # message_content is NOT required (and needs manual approval in Discord portal)
        intents = discord.Intents.default()
        # Explicitly ensure we have guild-related intents
        intents.guilds = True
        intents.guild_messages = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="MonolithBot - Jellyfin monitoring and announcements",
        )

        self.config = config
        self.test_mode = test_mode
        self._shutdown_event = asyncio.Event()

    async def setup_hook(self) -> None:
        """
        Perform async setup after the bot is logged in but before it connects.

        This method is called automatically by discord.py during bot startup.
        It loads all cogs (feature modules) and syncs slash commands with Discord.

        Raises:
            Exception: Logs but does not raise if a cog fails to load,
                allowing other cogs to still function.
        """
        logger.info("Loading cogs...")

        # List of cog modules to load
        # Add new cogs here as "bot.cogs.<name>"
        cogs_to_load = [
            "bot.cogs.announcements",
            "bot.cogs.health",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                # Log error but continue loading other cogs
                logger.error(f"Failed to load cog {cog}: {e}")

        # Sync slash commands with Discord
        # This makes commands available in the Discord UI
        logger.info("Syncing slash commands...")
        await self.tree.sync()

    async def on_ready(self) -> None:
        """
        Handle the bot becoming fully connected and ready.

        Called when the bot has successfully connected to Discord and
        received initial guild data. Logs connection info and validates
        that configured channels are accessible.
        """
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        # Validate announcement channel is accessible
        announcement_channel = self.get_channel(
            self.config.discord.announcement_channel_id
        )
        if announcement_channel:
            logger.info(f"Announcement channel: #{announcement_channel.name}")
        else:
            logger.warning(
                f"Could not find announcement channel with ID: "
                f"{self.config.discord.announcement_channel_id}"
            )

        # Validate alert channel is accessible
        alert_channel = self.get_channel(self.config.discord.alert_channel_id)
        if alert_channel:
            logger.info(f"Alert channel: #{alert_channel.name}")
        else:
            logger.warning(
                f"Could not find alert channel with ID: "
                f"{self.config.discord.alert_channel_id}"
            )

        # Run test mode actions if enabled
        if self.test_mode:
            await self._run_test_mode()

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """
        Handle uncaught exceptions in event handlers.

        This global error handler logs exceptions that occur in Discord
        event handlers (on_message, on_reaction_add, etc.) without crashing
        the bot.

        Args:
            event_method: Name of the event that raised the exception.
            *args: Positional arguments passed to the event handler.
            **kwargs: Keyword arguments passed to the event handler.
        """
        logger.exception(f"Error in event {event_method}")

    async def _run_test_mode(self) -> None:
        """
        Run test mode actions: health notification and content announcement.

        Called once on startup when --test flag is provided. Useful for
        testing without waiting for scheduled times.
        """
        logger.info("=== TEST MODE: Running health check and announcement ===")

        # Get the health cog and trigger a test notification
        health_cog = self.get_cog("Health")
        if health_cog:
            logger.info("TEST: Sending health status notification...")
            try:
                # Send an "online" notification for testing
                server_info = await health_cog.jellyfin.check_health()
                await health_cog._send_online_notification(server_info, None)
                logger.info("TEST: Health notification sent!")
            except Exception as e:
                logger.error(f"TEST: Health notification failed: {e}")
        else:
            logger.warning("TEST: Health cog not loaded")

        # Get the announcements cog and trigger an announcement
        announcements_cog = self.get_cog("Announcements")
        if announcements_cog:
            logger.info("TEST: Running content announcement...")
            try:
                count = await announcements_cog.announce_new_content()
                logger.info(f"TEST: Announced {count} items!")
            except Exception as e:
                logger.error(f"TEST: Announcement failed: {e}")
        else:
            logger.warning("TEST: Announcements cog not loaded")

        logger.info("=== TEST MODE COMPLETE ===")

    async def shutdown(self) -> None:
        """
        Gracefully shutdown the bot.

        Sets the shutdown event and closes the Discord connection.
        Cogs should handle their own cleanup in their `cog_unload` methods.
        """
        logger.info("Shutting down MonolithBot...")
        self._shutdown_event.set()
        await self.close()


def setup_logging(verbose: bool = False) -> None:
    """
    Configure the logging system for the bot.

    Sets up a consistent log format and configures log levels for both
    MonolithBot and third-party libraries.

    Args:
        verbose: If True, set log level to DEBUG for detailed output.
            If False (default), set to INFO for standard operation.

    Log Format:
        "2024-01-15 17:00:00 | INFO     | monolithbot | Message"
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Namespace containing:
            - config (Path): Path to the configuration JSON file
            - verbose (bool): Whether to enable debug logging
    """
    parser = argparse.ArgumentParser(
        description="MonolithBot - Discord bot for Jellyfin monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m bot.main                    Run with default config.json
  python -m bot.main --config my.json   Run with custom config file
  python -m bot.main --verbose          Run with debug logging
        """,
    )

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.json"),
        help="Path to configuration JSON file (default: config.json)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Run health check and announcement once on startup for testing",
    )

    return parser.parse_args()


async def run_bot(config: Config, test_mode: bool = False) -> None:
    """
    Run the bot with the given configuration.

    Creates the bot instance, sets up signal handlers for graceful shutdown,
    and starts the Discord connection. This function runs until the bot
    is shut down or encounters a fatal error.

    Args:
        config: Validated configuration object.
        test_mode: If True, run health check and announcement once on startup.

    Raises:
        SystemExit: On invalid Discord token or fatal errors.
    """
    bot = MonolithBot(config, test_mode=test_mode)

    def signal_handler() -> None:
        """Handle shutdown signals (SIGINT, SIGTERM)."""
        logger.info("Received shutdown signal")
        asyncio.create_task(bot.shutdown())

    # Register signal handlers for graceful shutdown (Unix only)
    # On Windows, KeyboardInterrupt is caught in main() instead
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        async with bot:
            await bot.start(config.discord.token)
    except discord.LoginFailure:
        logger.error("Invalid Discord token. Please check your configuration.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


def main() -> NoReturn | None:
    """
    Main entry point for MonolithBot.

    Orchestrates the startup sequence:
    1. Parse command-line arguments
    2. Configure logging
    3. Load and validate configuration
    4. Start the bot

    Returns:
        None on successful shutdown, or exits with code 1 on error.
    """
    args = parse_args()
    setup_logging(args.verbose)

    logger.info("Starting MonolithBot...")
    logger.info(f"Using config file: {args.config.absolute()}")

    # Load and validate configuration
    try:
        config = load_config(args.config)
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Log configuration summary (excluding sensitive values)
    logger.info(f"Jellyfin URL: {config.jellyfin.url}")
    logger.info(f"Announcement times: {', '.join(config.schedule.announcement_times)}")
    logger.info(f"Timezone: {config.schedule.timezone}")
    logger.info(f"Content types: {', '.join(config.content_types)}")

    # Run the bot
    try:
        asyncio.run(run_bot(config, test_mode=args.test))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")


if __name__ == "__main__":
    main()

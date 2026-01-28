"""
MonolithBot - Discord bot for Jellyfin server monitoring and announcements.

This module serves as the entry point for MonolithBot, handling:
- Command-line argument parsing
- Logging configuration
- Bot initialization and lifecycle management
- Graceful shutdown on SIGINT/SIGTERM

Usage:
    python -m bot.main                      # Run with default config.json
    python -m bot.main --config my.json     # Run with custom config file
    python -m bot.main --verbose            # Run with debug logging
    python -m bot.main --test               # Run all test modes on startup
    python -m bot.main --test-health        # Run health check test on startup
    python -m bot.main --test-announcement  # Run announcement test on startup

See Also:
    - bot.config: Configuration loading and validation
    - bot.cogs.announcements: Scheduled content announcements
    - bot.cogs.health: Server health monitoring
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import discord
from discord.ext import commands

from bot.config import Config, ConfigurationError, load_config

# Module-level logger for MonolithBot core
logger = logging.getLogger("monolithbot")


@dataclass
class TestModes:
    """
    Configuration for test modes that run on startup.

    Each test mode triggers a specific feature immediately on bot startup,
    useful for testing without waiting for scheduled times.

    Attributes:
        health: If True, run health check and send notification on startup.
        announcement: If True, run content announcement on startup.
    """

    health: bool = False
    announcement: bool = False

    @property
    def any_enabled(self) -> bool:
        """Check if any test mode is enabled."""
        return self.health or self.announcement

    @classmethod
    def all_enabled(cls) -> "TestModes":
        """Create a TestModes instance with all modes enabled."""
        return cls(health=True, announcement=True)


class MonolithBot(commands.Bot):
    """
    Main Discord bot class for MonolithBot.

    Extends discord.py's Bot class with Jellyfin monitoring capabilities.
    Configuration is stored on the instance and accessible to all cogs
    via `self.bot.config`.

    Attributes:
        config: The loaded configuration object containing Discord,
            Jellyfin, and scheduling settings.
        test_modes: TestModes instance controlling which tests run on startup.
        test_mode: Convenience property that returns True if any test mode is enabled.

    Example:
        >>> config = load_config(Path("config.json"))
        >>> bot = MonolithBot(config)
        >>> await bot.start(config.discord.token)
    """

    def __init__(
        self, config: Config, test_modes: TestModes | None = None
    ) -> None:
        """
        Initialize the MonolithBot instance.

        Args:
            config: Validated configuration object containing all settings
                required for bot operation (Discord token, Jellyfin URL, etc.)
            test_modes: TestModes instance specifying which tests to run on startup.
                If None, no tests are run.
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
        self._test_modes = test_modes or TestModes()
        self._shutdown_event = asyncio.Event()

    @property
    def test_mode(self) -> bool:
        """Check if any test mode is enabled (for backward compatibility)."""
        return self._test_modes.any_enabled

    @property
    def test_modes(self) -> TestModes:
        """Get the test modes configuration."""
        return self._test_modes

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

        # Run test mode actions if any are enabled
        if self._test_modes.any_enabled:
            await self._run_test_modes()

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

    async def _run_test_modes(self) -> None:
        """
        Run enabled test mode actions on startup.

        Called once on startup when any test flags are provided. Each test
        mode runs independently based on its flag.
        """
        enabled_modes = []
        if self._test_modes.health:
            enabled_modes.append("health")
        if self._test_modes.announcement:
            enabled_modes.append("announcement")

        logger.info(f"=== TEST MODE: Running {', '.join(enabled_modes)} ===")

        # Run health test if enabled
        if self._test_modes.health:
            await self._run_health_test()

        # Run announcement test if enabled
        if self._test_modes.announcement:
            await self._run_announcement_test()

        logger.info("=== TEST MODE COMPLETE ===")

    async def _run_health_test(self) -> None:
        """Run health check test and send notification."""
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

    async def _run_announcement_test(self) -> None:
        """Run content announcement test."""
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
            - test (bool): Run all test modes
            - test_health (bool): Run health check test
            - test_announcement (bool): Run announcement test
    """
    parser = argparse.ArgumentParser(
        description="MonolithBot - Discord bot for Jellyfin monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m bot.main                      Run with default config.json
  python -m bot.main --config my.json     Run with custom config file
  python -m bot.main --verbose            Run with debug logging
  python -m bot.main --test               Run all test modes on startup
  python -m bot.main --test-health        Run health check test only
  python -m bot.main --test-announcement  Run announcement test only
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

    # Test mode arguments
    test_group = parser.add_argument_group(
        "test modes",
        "Run specific features immediately on startup for testing",
    )

    test_group.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Run all test modes (health check + announcement)",
    )

    test_group.add_argument(
        "--test-health",
        action="store_true",
        help="Run health check and send notification on startup",
    )

    test_group.add_argument(
        "--test-announcement",
        action="store_true",
        help="Run content announcement on startup",
    )

    return parser.parse_args()


def build_test_modes(args: argparse.Namespace) -> TestModes:
    """
    Build TestModes from parsed command-line arguments.

    Args:
        args: Parsed argument namespace containing test flags.

    Returns:
        TestModes instance with appropriate flags set.
    """
    # If --test is set, enable all test modes
    if args.test:
        return TestModes.all_enabled()

    # Otherwise, enable individual test modes as specified
    return TestModes(
        health=args.test_health,
        announcement=args.test_announcement,
    )


async def run_bot(config: Config, test_modes: TestModes) -> None:
    """
    Run the bot with the given configuration.

    Creates the bot instance, sets up signal handlers for graceful shutdown,
    and starts the Discord connection. This function runs until the bot
    is shut down or encounters a fatal error.

    Args:
        config: Validated configuration object.
        test_modes: TestModes instance specifying which tests to run on startup.

    Raises:
        SystemExit: On invalid Discord token or fatal errors.
    """
    bot = MonolithBot(config, test_modes=test_modes)

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
    4. Build test modes from arguments
    5. Start the bot

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

    # Build test modes from command-line arguments
    test_modes = build_test_modes(args)
    if test_modes.any_enabled:
        enabled = []
        if test_modes.health:
            enabled.append("health")
        if test_modes.announcement:
            enabled.append("announcement")
        logger.info(f"Test modes enabled: {', '.join(enabled)}")

    # Run the bot
    try:
        asyncio.run(run_bot(config, test_modes=test_modes))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")


if __name__ == "__main__":
    main()

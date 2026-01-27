"""
MonolithBot - Discord bot for Jellyfin server monitoring and announcements.

Entry point and Discord bot initialization.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import discord
from discord.ext import commands

from bot.config import Config, ConfigurationError, load_config

logger = logging.getLogger("monolithbot")


class MonolithBot(commands.Bot):
    """Main bot class for MonolithBot."""

    def __init__(self, config: Config):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="MonolithBot - Jellyfin monitoring and announcements",
        )

        self.config = config
        self._shutdown_event = asyncio.Event()

    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        logger.info("Loading cogs...")

        cogs_to_load = [
            "bot.cogs.announcements",
            "bot.cogs.health",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"Failed to load cog {cog}: {e}")

        logger.info("Syncing slash commands...")
        await self.tree.sync()

    async def on_ready(self) -> None:
        """Called when the bot is connected and ready."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        announcement_channel = self.get_channel(self.config.discord.announcement_channel_id)
        if announcement_channel:
            logger.info(f"Announcement channel: #{announcement_channel.name}")
        else:
            logger.warning(
                f"Could not find announcement channel with ID: "
                f"{self.config.discord.announcement_channel_id}"
            )

        alert_channel = self.get_channel(self.config.discord.alert_channel_id)
        if alert_channel:
            logger.info(f"Alert channel: #{alert_channel.name}")
        else:
            logger.warning(
                f"Could not find alert channel with ID: {self.config.discord.alert_channel_id}"
            )

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Global error handler for events."""
        logger.exception(f"Error in event {event_method}")

    async def shutdown(self) -> None:
        """Gracefully shutdown the bot."""
        logger.info("Shutting down MonolithBot...")
        self._shutdown_event.set()
        await self.close()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the bot."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
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

    return parser.parse_args()


async def run_bot(config: Config) -> None:
    """Run the bot with the given configuration."""
    bot = MonolithBot(config)

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(bot.shutdown())

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


def main() -> None:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    logger.info("Starting MonolithBot...")
    logger.info(f"Using config file: {args.config.absolute()}")

    try:
        config = load_config(args.config)
        logger.info(f"Jellyfin URL: {config.jellyfin.url}")
        logger.info(f"Announcement times: {', '.join(config.schedule.announcement_times)}")
        logger.info(f"Timezone: {config.schedule.timezone}")
        logger.info(f"Content types: {', '.join(config.content_types)}")
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    try:
        asyncio.run(run_bot(config))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")


if __name__ == "__main__":
    main()

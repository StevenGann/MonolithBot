"""
MonolithBot - Discord bot for Jellyfin, Minecraft, and multi-service user registration.

This module serves as the entry point for MonolithBot, handling:
- Command-line argument parsing
- Logging configuration
- Bot initialization and lifecycle management
- Graceful shutdown on SIGINT/SIGTERM

Usage:
    python -m bot.main                        # Run with default config.json
    python -m bot.main --config my.json       # Run with custom config file
    python -m bot.main --verbose              # Run with debug logging
    python -m bot.main --test                 # Run all test modes on startup
    python -m bot.main --test-health          # Run Jellyfin health check test
    python -m bot.main --test-announcement    # Run Jellyfin announcement test
    python -m bot.main --test-minecraft       # Run Minecraft health check test

See Also:
    - bot.config: Configuration loading and validation
    - bot.cogs.jellyfin.announcements: Scheduled content announcements
    - bot.cogs.jellyfin.health: Jellyfin server health monitoring
    - bot.cogs.jellyfin.suggestions: Random content suggestions
    - bot.cogs.minecraft.health: Minecraft server health monitoring
    - bot.cogs.minecraft.players: Minecraft player join announcements
    - bot.cogs.registration.handler: Multi-service user registration via DM
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Optional

import discord
from discord.ext import commands

from bot.config import Config, ConfigurationError, load_config
from bot.services.jellyfin import JellyfinService
from bot.services.minecraft import MinecraftService
from bot.services.nextcloud import NextCloudService
from bot.services.navidrome import NavidromeService
from bot.services.organizr import OrganizrService
from bot.services.romm import RommService
from bot.services.registration import RegistrationService

if TYPE_CHECKING:
    pass

# Module-level logger for MonolithBot core
logger = logging.getLogger("monolithbot")


@dataclass
class TestModes:
    """
    Configuration for test modes that run on startup.

    Each test mode triggers a specific feature immediately on bot startup,
    useful for testing without waiting for scheduled times.

    Attributes:
        jf_health: If True, run Jellyfin health check and send notification on startup.
        jf_announcement: If True, run Jellyfin content announcement on startup.
        jf_suggestion: If True, run Jellyfin random suggestions on startup.
        mc_health: If True, run Minecraft health check test on startup.
        mc_announce: If True, run Minecraft player announcement test on startup.
    """

    jf_health: bool = False
    jf_announcement: bool = False
    jf_suggestion: bool = False
    mc_health: bool = False
    mc_announce: bool = False

    @property
    def any_enabled(self) -> bool:
        """Check if any test mode is enabled."""
        return (
            self.jf_health
            or self.jf_announcement
            or self.jf_suggestion
            or self.mc_health
            or self.mc_announce
        )

    @classmethod
    def all_enabled(cls) -> "TestModes":
        """Create a TestModes instance with all modes enabled."""
        return cls(
            jf_health=True,
            jf_announcement=True,
            jf_suggestion=True,
            mc_health=True,
            mc_announce=True,
        )


class MonolithBot(commands.Bot):
    """
    Main Discord bot class for MonolithBot.

    Extends discord.py's Bot class with Jellyfin and Minecraft monitoring.
    Configuration is stored on the instance and accessible to all cogs
    via `self.bot.config`.

    Attributes:
        config: The loaded configuration object containing Discord,
            Jellyfin, Minecraft, and scheduling settings.
        jellyfin_service: Shared JellyfinService instance for Jellyfin cogs.
            None if Jellyfin integration is disabled.
        minecraft_service: Shared MinecraftService instance for Minecraft cogs.
            None if Minecraft integration is disabled.
        nextcloud_service: Shared NextCloudService instance for user registration.
            None if NextCloud integration is disabled.
        navidrome_service: Shared NavidromeService instance for user registration.
            None if Navidrome integration is disabled.
        organizr_service: Shared OrganizrService instance for user registration.
            None if Organizr integration is disabled.
        romm_service: Shared RommService instance for user registration.
            None if Romm integration is disabled.
        registration_service: Shared RegistrationService instance for multi-service registration.
            None if registration feature is disabled.
        test_modes: TestModes instance controlling which tests run on startup.
        test_mode: Convenience property that returns True if any test mode is enabled.

    Example:
        >>> config = load_config(Path("config.json"))
        >>> bot = MonolithBot(config)
        >>> await bot.start(config.discord.token)
    """

    def __init__(self, config: Config, test_modes: TestModes | None = None) -> None:
        """
        Initialize the MonolithBot instance.

        Args:
            config: Validated configuration object containing all settings
                required for bot operation (Discord token, Jellyfin URL, etc.)
            test_modes: TestModes instance specifying which tests to run on startup.
                If None, no tests are run.
        """
        # Configure Discord intents
        # We need default intents for slash commands and sending messages
        intents = discord.Intents.default()
        # Explicitly ensure we have guild-related intents
        intents.guilds = True
        intents.guild_messages = True
        # Enable DM-related intents for registration feature
        intents.dm_messages = True
        intents.message_content = True  # Required to read DM content

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="MonolithBot - Jellyfin monitoring and announcements",
        )

        self.config = config
        self._test_modes = test_modes or TestModes()
        self._shutdown_event = asyncio.Event()

        # Shared service instances (initialized in setup_hook if enabled)
        self.jellyfin_service: Optional[JellyfinService] = None
        self.minecraft_service: Optional[MinecraftService] = None
        self.nextcloud_service: Optional[NextCloudService] = None
        self.navidrome_service: Optional[NavidromeService] = None
        self.organizr_service: Optional[OrganizrService] = None
        self.romm_service: Optional[RommService] = None
        self.registration_service: Optional[RegistrationService] = None
        self._admin_ui_runner = None  # aiohttp AppRunner when admin UI is enabled

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
        It initializes shared services, loads all cogs (feature modules), and
        syncs slash commands with Discord.

        Raises:
            Exception: Logs but does not raise if a cog fails to load,
                allowing other cogs to still function.
        """
        # Initialize shared services
        if self.config.jellyfin.enabled:
            self.jellyfin_service = JellyfinService(
                urls=self.config.jellyfin.urls,
                api_key=self.config.jellyfin.api_key,
            )
            logger.info(
                f"Jellyfin service initialized with {len(self.config.jellyfin.urls)} URL(s)"
            )

        if self.config.minecraft.enabled:
            self.minecraft_service = MinecraftService(
                servers=self.config.minecraft.servers,
            )
            logger.info(
                f"Minecraft service initialized with {len(self.config.minecraft.servers)} server(s)"
            )

        # Initialize registration-related services
        if self.config.nextcloud.enabled:
            self.nextcloud_service = NextCloudService(
                urls=self.config.nextcloud.urls,
                admin_user=self.config.nextcloud.admin_user,
                admin_password=self.config.nextcloud.admin_password,
            )
            logger.info(
                f"NextCloud service initialized with {len(self.config.nextcloud.urls)} URL(s)"
            )

        if self.config.navidrome.enabled:
            self.navidrome_service = NavidromeService(
                urls=self.config.navidrome.urls,
                admin_user=self.config.navidrome.admin_user,
                admin_password=self.config.navidrome.admin_password,
            )
            logger.info(
                f"Navidrome service initialized with {len(self.config.navidrome.urls)} URL(s)"
            )

        if self.config.organizr.enabled:
            self.organizr_service = OrganizrService(
                urls=self.config.organizr.urls,
                admin_user=self.config.organizr.admin_user,
                admin_password=self.config.organizr.admin_password,
            )
            logger.info(
                f"Organizr service initialized with {len(self.config.organizr.urls)} URL(s)"
            )

        if self.config.romm.enabled:
            self.romm_service = RommService(
                urls=self.config.romm.urls,
                admin_user=self.config.romm.admin_user,
                admin_password=self.config.romm.admin_password,
            )
            logger.info(
                f"Romm service initialized with {len(self.config.romm.urls)} URL(s)"
            )

        # Initialize the registration orchestrator service
        if self.config.registration.enabled:
            self.registration_service = RegistrationService(
                jellyfin_service=self.jellyfin_service,
                nextcloud_service=self.nextcloud_service,
                navidrome_service=self.navidrome_service,
                organizr_service=self.organizr_service,
                romm_service=self.romm_service,
            )
            logger.info("Registration service initialized")

        logger.info("Loading cogs...")

        # List of cog modules to load
        # Jellyfin cogs are only loaded if Jellyfin is enabled
        cogs_to_load = []

        if self.config.jellyfin.enabled:
            cogs_to_load.extend(
                [
                    "bot.cogs.jellyfin.announcements",
                    "bot.cogs.jellyfin.health",
                    "bot.cogs.jellyfin.suggestions",
                ]
            )
            logger.info("Jellyfin integration enabled - loading Jellyfin cogs")
        else:
            logger.info("Jellyfin integration disabled - skipping Jellyfin cogs")

        if self.config.minecraft.enabled:
            cogs_to_load.extend(
                [
                    "bot.cogs.minecraft.health",
                    "bot.cogs.minecraft.players",
                ]
            )
            logger.info("Minecraft integration enabled - loading Minecraft cogs")
        else:
            logger.info("Minecraft integration disabled - skipping Minecraft cogs")

        if self.config.registration.enabled:
            cogs_to_load.append("bot.cogs.registration.handler")
            logger.info("Registration feature enabled - loading Registration cog")
        else:
            logger.info("Registration feature disabled - skipping Registration cog")

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

        # Validate Jellyfin channels when enabled
        if self.config.jellyfin.enabled:
            announcement_channel = self.get_channel(
                self.config.jellyfin.announcement_channel_id
            )
            if announcement_channel:
                logger.info(
                    f"Jellyfin announcement channel: #{announcement_channel.name}"
                )
            else:
                logger.warning(
                    f"Could not find Jellyfin announcement channel with ID: "
                    f"{self.config.jellyfin.announcement_channel_id}"
                )
            alert_channel = self.get_channel(self.config.jellyfin.alert_channel_id)
            if alert_channel:
                logger.info(f"Jellyfin alert channel: #{alert_channel.name}")
            else:
                logger.warning(
                    f"Could not find Jellyfin alert channel with ID: "
                    f"{self.config.jellyfin.alert_channel_id}"
                )

        # Start admin UI HTTP server if enabled
        if getattr(self.config, "admin_ui", None) and self.config.admin_ui.enabled:
            try:
                from aiohttp import web
                from bot.admin_ui import create_app

                app = create_app(bot=self, config=self.config)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(
                    runner,
                    self.config.admin_ui.host,
                    self.config.admin_ui.port,
                )
                await site.start()
                self._admin_ui_runner = runner
                logger.info(
                    f"Admin UI: http://{self.config.admin_ui.host}:{self.config.admin_ui.port}/admin/"
                )
            except Exception as e:
                logger.exception(f"Failed to start admin UI: {e}")

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
        if self._test_modes.jf_health:
            enabled_modes.append("jf-health")
        if self._test_modes.jf_announcement:
            enabled_modes.append("jf-announcement")
        if self._test_modes.jf_suggestion:
            enabled_modes.append("jf-suggestion")
        if self._test_modes.mc_health:
            enabled_modes.append("mc-health")
        if self._test_modes.mc_announce:
            enabled_modes.append("mc-announce")

        logger.info(f"=== TEST MODE: Running {', '.join(enabled_modes)} ===")

        # Run Jellyfin tests if enabled
        if self.config.jellyfin.enabled:
            if self._test_modes.jf_health:
                await self._run_jf_health_test()

            if self._test_modes.jf_announcement:
                await self._run_jf_announcement_test()

            if self._test_modes.jf_suggestion:
                await self._run_jf_suggestion_test()
        else:
            if (
                self._test_modes.jf_health
                or self._test_modes.jf_announcement
                or self._test_modes.jf_suggestion
            ):
                logger.warning("Jellyfin is disabled - skipping Jellyfin test modes")

        # Run Minecraft tests if enabled
        if self.config.minecraft.enabled:
            if self._test_modes.mc_health:
                await self._run_mc_health_test()

            if self._test_modes.mc_announce:
                await self._run_mc_announce_test()
        else:
            if self._test_modes.mc_health or self._test_modes.mc_announce:
                logger.warning("Minecraft is disabled - skipping Minecraft test modes")

        logger.info("=== TEST MODE COMPLETE ===")

    async def _run_jf_health_test(self) -> None:
        """Run Jellyfin health check test and send notification."""
        health_cog = self.get_cog("JellyfinHealth")
        if health_cog:
            logger.info("TEST: Sending health status notification...")
            try:
                # Use shared service for health check
                if self.jellyfin_service:
                    server_info = await self.jellyfin_service.check_health()
                    await health_cog._send_online_notification(server_info, None)
                    logger.info(
                        f"TEST: Health notification sent! "
                        f"(active URL: {self.jellyfin_service.active_url})"
                    )
                else:
                    logger.error("TEST: Jellyfin service not available")
            except Exception as e:
                logger.error(f"TEST: Health notification failed: {e}")
        else:
            logger.warning("TEST: JellyfinHealth cog not loaded")

    async def _run_jf_announcement_test(self) -> None:
        """Run Jellyfin content announcement test."""
        announcements_cog = self.get_cog("JellyfinAnnouncements")
        if announcements_cog:
            logger.info("TEST: Running content announcement...")
            try:
                count = await announcements_cog.announce_new_content()
                logger.info(f"TEST: Announced {count} items!")
            except Exception as e:
                logger.error(f"TEST: Announcement failed: {e}")
        else:
            logger.warning("TEST: JellyfinAnnouncements cog not loaded")

    async def _run_jf_suggestion_test(self) -> None:
        """Run Jellyfin random suggestion test."""
        suggestions_cog = self.get_cog("JellyfinSuggestions")
        if suggestions_cog:
            logger.info("TEST: Running random suggestions...")
            try:
                count = await suggestions_cog.post_random_suggestions()
                logger.info(f"TEST: Posted {count} suggestions!")
            except Exception as e:
                logger.error(f"TEST: Suggestion failed: {e}")
        else:
            logger.warning("TEST: JellyfinSuggestions cog not loaded")

    async def _run_mc_health_test(self) -> None:
        """Run Minecraft health check test."""
        health_cog = self.get_cog("MinecraftHealth")
        if health_cog and self.minecraft_service:
            logger.info("TEST: Running Minecraft health checks...")
            try:
                for server_name in self.minecraft_service.get_server_names():
                    status = await self.minecraft_service.check_health(server_name)
                    state = self.minecraft_service.get_server_state(server_name)
                    active_url = state.active_url if state else "unknown"
                    logger.info(
                        f"TEST: {server_name}: {status.player_count}/{status.max_players} players, "
                        f"v{status.version} (via {active_url})"
                    )
                    await health_cog._send_online_notification(
                        server_name, status, None
                    )
                logger.info("TEST: Minecraft health checks complete!")
            except Exception as e:
                logger.error(f"TEST: Minecraft health check failed: {e}")
        else:
            logger.warning(
                "TEST: MinecraftHealth cog not loaded or service unavailable"
            )

    async def _run_mc_announce_test(self) -> None:
        """Run Minecraft player announcement test."""
        players_cog = self.get_cog("MinecraftPlayers")
        if players_cog and self.minecraft_service:
            logger.info("TEST: Running Minecraft player announcement test...")
            try:
                for server_name in self.minecraft_service.get_server_names():
                    # Get current status
                    status = await self.minecraft_service.get_status(server_name)

                    # Simulate a test player join announcement
                    test_players = {"TestPlayer"}
                    logger.info(f"TEST: Simulating player join on {server_name}...")
                    await players_cog._send_join_announcement(
                        server_name, test_players, status
                    )
                logger.info("TEST: Minecraft player announcements complete!")
            except Exception as e:
                logger.error(f"TEST: Minecraft player announcement failed: {e}")
        else:
            logger.warning(
                "TEST: MinecraftPlayers cog not loaded or service unavailable"
            )

    async def shutdown(self) -> None:
        """
        Gracefully shutdown the bot.

        Sets the shutdown event, closes shared services, and closes the
        Discord connection. Cogs should handle their own cleanup in their
        `cog_unload` methods.
        """
        logger.info("Shutting down MonolithBot...")
        self._shutdown_event.set()

        # Close shared services
        if self.jellyfin_service:
            await self.jellyfin_service.close()
            logger.info("Jellyfin service closed")

        if self.nextcloud_service:
            await self.nextcloud_service.close()
            logger.info("NextCloud service closed")

        if self.navidrome_service:
            await self.navidrome_service.close()
            logger.info("Navidrome service closed")

        if self.organizr_service:
            await self.organizr_service.close()
            logger.info("Organizr service closed")

        if self.romm_service:
            await self.romm_service.close()
            logger.info("Romm service closed")

        # MinecraftService doesn't need explicit close (no persistent connections)
        if self.minecraft_service:
            logger.info("Minecraft service stopped")

        if getattr(self, "_admin_ui_runner", None):
            await self._admin_ui_runner.cleanup()
            self._admin_ui_runner = None
            logger.info("Admin UI stopped")

        await self.close()


def setup_logging(
    config: Optional[Config] = None, verbose: bool = False
) -> Optional[Path]:
    """
    Configure the logging system for the bot.

    Sets up file-based logging with daily rotation and console output.
    Uses the new logging service for structured log output with tags.

    Args:
        config: Configuration object containing logging settings.
            If None, falls back to basic console logging.
        verbose: If True, override log level to DEBUG for detailed output.
            If False (default), use level from config or INFO.

    Returns:
        Path to the log file if file logging is enabled, None otherwise.

    Log Format:
        "2024-01-15 17:00:00 | INFO     | CORE       | Message"

    Log Files:
        Created in config.logging.log_directory with naming format:
        MonolithBot.YYYY-MM-DD.HH-MM-SS.log
    """
    from bot.services.logging_service import setup_file_logging

    # Determine settings from config or use defaults
    if config is not None:
        log_dir = config.logging.log_directory
        log_level = "DEBUG" if verbose else config.logging.log_level
        log_to_console = config.logging.log_to_console
        log_to_file = config.logging.log_to_file
        # Use Jellyfin schedule timezone if available, else UTC
        timezone = (
            config.jellyfin.schedule.timezone if config.jellyfin.enabled else "UTC"
        )
    else:
        # Fallback for basic logging before config is loaded
        log_dir = "logs"
        log_level = "DEBUG" if verbose else "INFO"
        log_to_console = True
        log_to_file = False  # Don't create files without proper config
        timezone = "UTC"

    log_path = setup_file_logging(
        log_dir=log_dir,
        timezone=timezone,
        level=log_level,
        log_to_console=log_to_console,
        log_to_file=log_to_file,
    )

    return log_path


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
  python -m bot.main                         Run with default config.json
  python -m bot.main --config my.json        Run with custom config file
  python -m bot.main --verbose               Run with debug logging
  python -m bot.main --test                  Run all test modes on startup
  python -m bot.main --test-jellyfin         Run all Jellyfin test modes
  python -m bot.main --test-jf-health        Run Jellyfin health check test
  python -m bot.main --test-minecraft        Run all Minecraft test modes
  python -m bot.main --test-mc-health        Run Minecraft health check test
  python -m bot.main --test-mc-announce      Run Minecraft player announcement test
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
        help="Run all test modes (Jellyfin + Minecraft)",
    )

    test_group.add_argument(
        "--test-jellyfin",
        action="store_true",
        help="Run all Jellyfin test modes (health + announcement + suggestion)",
    )

    test_group.add_argument(
        "--test-jf-health",
        action="store_true",
        help="Run Jellyfin health check and send notification on startup",
    )

    test_group.add_argument(
        "--test-jf-announcement",
        action="store_true",
        help="Run Jellyfin content announcement on startup",
    )

    test_group.add_argument(
        "--test-jf-suggestion",
        action="store_true",
        help="Run Jellyfin random suggestions on startup",
    )

    test_group.add_argument(
        "--test-minecraft",
        action="store_true",
        help="Run all Minecraft test modes (health + announce)",
    )

    test_group.add_argument(
        "--test-mc-health",
        action="store_true",
        help="Run Minecraft health check on startup",
    )

    test_group.add_argument(
        "--test-mc-announce",
        action="store_true",
        help="Run Minecraft player announcement test on startup",
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

    # If --test-jellyfin is set, enable all Jellyfin test modes
    jf_health = args.test_jf_health
    jf_announcement = args.test_jf_announcement
    jf_suggestion = args.test_jf_suggestion
    if args.test_jellyfin:
        jf_health = True
        jf_announcement = True
        jf_suggestion = True

    # If --test-minecraft is set, enable all Minecraft test modes
    mc_health = args.test_mc_health
    mc_announce = args.test_mc_announce
    if args.test_minecraft:
        mc_health = True
        mc_announce = True

    return TestModes(
        jf_health=jf_health,
        jf_announcement=jf_announcement,
        jf_suggestion=jf_suggestion,
        mc_health=mc_health,
        mc_announce=mc_announce,
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
    2. Load and validate configuration
    3. Configure logging with config settings
    4. Build test modes from arguments
    5. Start the bot

    Returns:
        None on successful shutdown, or exits with code 1 on error.
    """
    args = parse_args()

    # Setup basic console logging first to capture config loading errors
    setup_logging(config=None, verbose=args.verbose)

    logger.info("Starting MonolithBot...")
    logger.info(f"Using config file: {args.config.absolute()}")

    # Load and validate configuration
    try:
        config = load_config(args.config)
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Now reconfigure logging with full config (file logging, timezone, etc.)
    log_path = setup_logging(config=config, verbose=args.verbose)
    if log_path:
        logger.info(f"Logging to file: {log_path}")

    # Log configuration summary (excluding sensitive values)
    logger.info(f"Jellyfin enabled: {config.jellyfin.enabled}")
    if config.jellyfin.enabled:
        if len(config.jellyfin.urls) > 1:
            logger.info(
                f"Jellyfin URLs ({len(config.jellyfin.urls)} configured for failover):"
            )
            for i, url in enumerate(config.jellyfin.urls):
                logger.info(f"  [{i + 1}] {url}")
        else:
            logger.info(f"Jellyfin URL: {config.jellyfin.url}")
        logger.info(
            f"Announcement times: {', '.join(config.jellyfin.schedule.announcement_times)}"
        )
        logger.info(
            f"Suggestion times: {', '.join(config.jellyfin.schedule.suggestion_times)}"
        )
        logger.info(f"Timezone: {config.jellyfin.schedule.timezone}")
        logger.info(f"Content types: {', '.join(config.jellyfin.content_types)}")

    logger.info(f"Registration enabled: {config.registration.enabled}")
    if config.registration.enabled:
        enabled_services = []
        if config.jellyfin.enabled:
            enabled_services.append("Jellyfin")
        if config.nextcloud.enabled:
            enabled_services.append("NextCloud")
        if config.navidrome.enabled:
            enabled_services.append("Navidrome")
        if config.romm.enabled:
            enabled_services.append("Romm")
        if enabled_services:
            logger.info(f"Registration services: {', '.join(enabled_services)}")
        else:
            logger.warning("Registration enabled but no services are configured!")

    # Build test modes from command-line arguments
    test_modes = build_test_modes(args)
    if test_modes.any_enabled:
        enabled = []
        if test_modes.jf_health:
            enabled.append("jf-health")
        if test_modes.jf_announcement:
            enabled.append("jf-announcement")
        if test_modes.jf_suggestion:
            enabled.append("jf-suggestion")
        if test_modes.mc_health:
            enabled.append("mc-health")
        if test_modes.mc_announce:
            enabled.append("mc-announce")
        logger.info(f"Test modes enabled: {', '.join(enabled)}")

    # Run the bot
    try:
        asyncio.run(run_bot(config, test_modes=test_modes))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")


if __name__ == "__main__":
    main()

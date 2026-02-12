"""
Registration DM handler cog for MonolithBot.

This cog handles direct message interactions for user registration across
multiple services (Jellyfin, NextCloud, Navidrome, Organizr, Romm).

Key Features:
    - DM-based registration flow
    - Username and email validation
    - Rich embed responses with registration results
    - Password delivered securely via DM only
    - Persistent tracking of Discord user to service account mappings
    - Password reset functionality

Usage Flow:
    1. User DMs the bot: "register myusername myemail@example.com"
    2. Bot checks if user already registered (via UserRegistry)
    3. Bot validates input and creates accounts on all enabled services
    4. Bot saves the mapping and responds with registration results

Commands:
    - register <username> <email>: Register on all services
    - /register: Slash command version
    - reset-password: Reset password on all services
    - /reset-password: Slash command version

Configuration:
    Requires `registration.enabled = true` in config.
    At least one service (Jellyfin, NextCloud, Navidrome, Organizr, Romm) must be enabled.

See Also:
    - bot.services.registration: Registration orchestrator
    - bot.services.user_registry: User mapping persistence
    - bot.config: Registration and service configuration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.registration import (
    PasswordResetResult,
    RegistrationResult,
    RegistrationService,
    ValidationError,
    validate_email,
    validate_username,
)
from bot.services.user_registry import UserRegistry

if TYPE_CHECKING:
    from bot.main import MonolithBot

# Module logger
logger = logging.getLogger("monolithbot.registration")

# Colors for embeds
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_WARNING = discord.Color.orange()
COLOR_INFO = discord.Color.blue()


class RegistrationCog(commands.Cog, name="Registration"):
    """
    Discord cog for handling user registration via DMs.

    This cog listens for DMs containing registration requests and
    orchestrates account creation across all enabled services.

    The registration flow:
    1. User sends DM with username and email
    2. Cog validates input format
    3. Cog calls RegistrationService to create accounts
    4. Cog sends embed with results and password (DM only)

    Attributes:
        bot: Reference to the MonolithBot instance.
        registration_service: Service for coordinating registration.

    Security:
        - Passwords are only sent via DM, never in guild channels
        - Usernames and emails are validated before processing
        - Rate limiting can be added to prevent abuse

    Example:
        User DMs: "register johndoe john@example.com"
        Bot responds with embed showing results for each service
    """

    def __init__(self, bot: "MonolithBot") -> None:
        """
        Initialize the registration cog.

        Args:
            bot: The MonolithBot instance. Used to access configuration
                and shared services.
        """
        self.bot = bot
        self.registration_service: Optional[RegistrationService] = None
        self.user_registry: Optional[UserRegistry] = None

    async def cog_load(self) -> None:
        """
        Initialize resources when the cog is loaded.

        Creates the RegistrationService with all enabled service instances
        and loads the user registry.
        """
        # Build the registration service with available services
        self.registration_service = RegistrationService(
            jellyfin_service=self.bot.jellyfin_service,
            nextcloud_service=getattr(self.bot, "nextcloud_service", None),
            navidrome_service=getattr(self.bot, "navidrome_service", None),
            organizr_service=getattr(self.bot, "organizr_service", None),
            romm_service=getattr(self.bot, "romm_service", None),
        )

        enabled = self.registration_service.enabled_services
        if enabled:
            logger.info(f"Registration enabled for services: {', '.join(enabled)}")
        else:
            logger.warning("Registration cog loaded but no services are enabled")

        # Load the user registry
        registry_path = self.bot.config.registration.registry_file
        self.user_registry = UserRegistry(registry_path)
        await self.user_registry.load()
        logger.info(
            f"User registry loaded: {self.user_registry.user_count} registered users"
        )

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Save the registry before unloading
        if self.user_registry:
            await self.user_registry.save()
        self.registration_service = None
        self.user_registry = None

    # -------------------------------------------------------------------------
    # Event Listeners
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listen for DM messages containing registration requests.

        Parses messages for the pattern:
            register <username> <email>

        Args:
            message: The Discord message to process.
        """
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # Only process DMs
        if not isinstance(message.channel, discord.DMChannel):
            return

        # Check if registration is enabled
        if not self.bot.config.registration.enabled:
            return

        # Parse the message for registration command
        content = message.content.strip()

        # Check for "register" prefix (case-insensitive)
        if not content.lower().startswith("register"):
            # Send help message if DM doesn't start with register
            await self._send_help(message.channel)
            return

        # Extract arguments after "register"
        args = content[8:].strip()  # Remove "register" prefix

        # Parse username, email, and optional password
        parts = args.split()

        if len(parts) < 2:
            await self._send_usage_error(message.channel)
            return

        username = parts[0]
        email = parts[1]
        password = parts[2] if len(parts) >= 3 else None

        # Process the registration
        await self._process_registration(
            message.channel, message.author, username, email, password
        )

    # -------------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------------

    @app_commands.command(
        name="register",
        description="Register for an account on Monolith services",
    )
    @app_commands.describe(
        username="Your desired username (3-32 characters, letters/numbers/underscores)",
        email="Your email address",
        password="Optional: Your desired password (leave empty to generate a secure one)",
    )
    async def register_command(
        self,
        interaction: discord.Interaction,
        username: str,
        email: str,
        password: Optional[str] = None,
    ) -> None:
        """
        Slash command for user registration.

        This command can be used in DMs or guilds, but the password
        will only be shown in DMs for security.

        Args:
            interaction: The Discord interaction.
            username: Desired username.
            email: User's email address.
            password: Optional desired password. If not provided, a secure one is generated.
        """
        # Check if registration is enabled
        if not self.bot.config.registration.enabled:
            await interaction.response.send_message(
                "❌ Registration is currently disabled.",
                ephemeral=True,
            )
            return

        # Defer response since registration may take a moment
        await interaction.response.defer(ephemeral=True)

        # Check if this is a DM
        is_dm = isinstance(interaction.channel, discord.DMChannel)

        if not is_dm:
            # In guild, redirect to DM
            password_hint = f" {password}" if password else ""
            await interaction.followup.send(
                "🔒 For security, please use this command in a DM with me.\n"
                f"Send me a DM with: `register {username} {email}{password_hint}`",
                ephemeral=True,
            )
            return

        # Process registration
        await self._process_registration_interaction(
            interaction, username, email, password
        )

    @app_commands.command(
        name="help",
        description="Get help with available commands (sends a DM)",
    )
    async def help_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Slash command for getting help.

        Sends a DM to the user with all available commands and their descriptions.

        Args:
            interaction: The Discord interaction.
        """
        await interaction.response.defer(ephemeral=True)

        # Try to send DM to user
        try:
            dm_channel = await interaction.user.create_dm()
            embed = self._create_full_help_embed()
            await dm_channel.send(embed=embed)

            await interaction.followup.send(
                "📬 I've sent you a DM with the help information!",
                ephemeral=True,
            )
        except discord.Forbidden:
            # User has DMs disabled
            await interaction.followup.send(
                "❌ I couldn't send you a DM. Please enable DMs from server members and try again.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error sending help DM: {e}")
            await interaction.followup.send(
                "❌ An error occurred while sending the help message.",
                ephemeral=True,
            )

    @app_commands.command(
        name="resetpassword",
        description="Reset your password on all Monolith services",
    )
    @app_commands.describe(
        password="Optional: Your desired new password (leave empty to generate one)",
    )
    async def resetpassword_command(
        self,
        interaction: discord.Interaction,
        password: Optional[str] = None,
    ) -> None:
        """
        Slash command for password reset.

        This command can only be used by registered users. The new password
        will only be shown in DMs for security.

        Args:
            interaction: The Discord interaction.
            password: Optional new password. If not provided, one will be generated.
        """
        # Check if registration is enabled
        if not self.bot.config.registration.enabled:
            await interaction.response.send_message(
                "❌ Registration is currently disabled.",
                ephemeral=True,
            )
            return

        # Defer response since reset may take a moment
        await interaction.response.defer(ephemeral=True)

        # Check if this is a DM
        is_dm = isinstance(interaction.channel, discord.DMChannel)

        if not is_dm:
            # In guild, redirect to DM
            await interaction.followup.send(
                "🔒 For security, please use this command in a DM with me.",
                ephemeral=True,
            )
            return

        # Process password reset
        await self._process_password_reset_interaction(interaction, password)

    # -------------------------------------------------------------------------
    # Registration Processing
    # -------------------------------------------------------------------------

    async def _process_registration(
        self,
        channel: discord.DMChannel,
        user: discord.User,
        username: str,
        email: str,
        password: Optional[str] = None,
    ) -> None:
        """
        Process a registration request from a DM message.

        Args:
            channel: The DM channel to respond in.
            user: The Discord user requesting registration.
            username: Desired username.
            email: User's email address.
            password: Optional desired password. If not provided, one is generated.
        """
        logger.info(
            f"Registration request from {user.name} ({user.id}): "
            f"username={username}, email={email}"
        )

        # Validate inputs
        try:
            username = validate_username(username)
            email = validate_email(email)
        except ValidationError as e:
            await self._send_validation_error(channel, str(e))
            return

        # If Discord user already registered, continue registration on any services
        # where they don't yet exist (e.g., retry after fixing a failed service)
        already_registered = (
            self.user_registry is not None
            and self.user_registry.is_discord_user_registered(user.id)
        )
        if already_registered:
            existing = self.user_registry.get_by_discord_id(user.id)
            # Use existing credentials to attempt registration on missing services
            username = existing.username
            email = existing.email
            logger.info(
                f"Continuing registration for existing user {user.name} ({user.id}): "
                f"username={username}"
            )
        else:
            # Check if username is already taken by another user
            if self.user_registry and self.user_registry.is_username_taken(username):
                await self._send_username_taken_error(channel, username)
                return

        # Show typing indicator while processing
        async with channel.typing():
            # Perform registration
            try:
                result = await self.registration_service.register_user(
                    username, email, password
                )
            except Exception as e:
                logger.error(f"Registration failed for {username}: {e}")
                await self._send_error(
                    channel, "An unexpected error occurred during registration."
                )
                return

        # Save to registry if any registration succeeded
        if result.any_success and self.user_registry:
            # Include services where user already existed (they're still "registered")
            all_registered = [sr.service_name for sr in result.services if sr.success]

            if already_registered:
                self.user_registry.update_services(user.id, all_registered)
                logger.info(f"Updated registration for {username}: {all_registered}")
            else:
                self.user_registry.add_user(
                    discord_id=user.id,
                    discord_name=str(user),
                    username=username,
                    email=email,
                    services=all_registered,
                )
                logger.info(f"Saved registration to registry: {user} -> {username}")
            await self.user_registry.save()

        # Send result embed
        await self._send_result_embed(channel, result)

    async def _process_registration_interaction(
        self,
        interaction: discord.Interaction,
        username: str,
        email: str,
        password: Optional[str] = None,
    ) -> None:
        """
        Process a registration request from a slash command.

        Args:
            interaction: The Discord interaction.
            username: Desired username.
            email: User's email address.
            password: Optional desired password. If not provided, one is generated.
        """
        user = interaction.user
        logger.info(
            f"Registration request from {user.name} ({user.id}): "
            f"username={username}, email={email}"
        )

        # Validate inputs
        try:
            username = validate_username(username)
            email = validate_email(email)
        except ValidationError as e:
            await interaction.followup.send(
                embed=self._create_error_embed(str(e)),
                ephemeral=True,
            )
            return

        # If Discord user already registered, continue registration on any services
        # where they don't yet exist
        already_registered = (
            self.user_registry is not None
            and self.user_registry.is_discord_user_registered(user.id)
        )
        if already_registered:
            existing = self.user_registry.get_by_discord_id(user.id)
            username = existing.username
            email = existing.email
            logger.info(
                f"Continuing registration for existing user {user.name} ({user.id}): "
                f"username={username}"
            )
        else:
            # Check if username is already taken by another user
            if self.user_registry and self.user_registry.is_username_taken(username):
                await interaction.followup.send(
                    embed=self._create_username_taken_embed(username),
                    ephemeral=True,
                )
                return

        # Perform registration
        try:
            result = await self.registration_service.register_user(
                username, email, password
            )
        except Exception as e:
            logger.error(f"Registration failed for {username}: {e}")
            await interaction.followup.send(
                embed=self._create_error_embed(
                    "An unexpected error occurred during registration."
                ),
                ephemeral=True,
            )
            return

        # Save to registry if any registration succeeded
        if result.any_success and self.user_registry:
            all_registered = [sr.service_name for sr in result.services if sr.success]

            if already_registered:
                self.user_registry.update_services(user.id, all_registered)
                logger.info(f"Updated registration for {username}: {all_registered}")
            else:
                self.user_registry.add_user(
                    discord_id=user.id,
                    discord_name=str(user),
                    username=username,
                    email=email,
                    services=all_registered,
                )
                logger.info(f"Saved registration to registry: {user} -> {username}")
            await self.user_registry.save()

        # Send result embed
        embed = self._create_result_embed(result)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _process_password_reset_interaction(
        self,
        interaction: discord.Interaction,
        password: Optional[str] = None,
    ) -> None:
        """
        Process a password reset request from a slash command.

        Args:
            interaction: The Discord interaction.
            password: Optional new password. If not provided, one will be generated.
        """
        user = interaction.user
        logger.info(f"Password reset request from {user.name} ({user.id})")

        # Check if user is registered
        if not self.user_registry:
            await interaction.followup.send(
                embed=self._create_error_embed("User registry is not available."),
                ephemeral=True,
            )
            return

        if not self.user_registry.is_discord_user_registered(user.id):
            await interaction.followup.send(
                embed=self._create_not_registered_embed(),
                ephemeral=True,
            )
            return

        # Get the registered user info
        registered_user = self.user_registry.get_by_discord_id(user.id)
        if not registered_user:
            await interaction.followup.send(
                embed=self._create_error_embed("Could not find your registration."),
                ephemeral=True,
            )
            return

        username = registered_user.username

        # Perform password reset
        try:
            result = await self.registration_service.reset_password(username, password)
        except ValidationError as e:
            await interaction.followup.send(
                embed=self._create_error_embed(str(e)),
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.error(f"Password reset failed for {username}: {e}")
            await interaction.followup.send(
                embed=self._create_error_embed(
                    "An unexpected error occurred during password reset."
                ),
                ephemeral=True,
            )
            return

        # Send result embed
        embed = self._create_password_reset_embed(result)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # -------------------------------------------------------------------------
    # Embed Builders
    # -------------------------------------------------------------------------

    def _create_result_embed(self, result: RegistrationResult) -> discord.Embed:
        """
        Create an embed displaying registration results.

        Args:
            result: The registration result to display.

        Returns:
            Discord embed with results.
        """
        # Determine overall status
        if result.all_success and result.new_registrations:
            title = "🎉 Registration Complete!"
            color = COLOR_SUCCESS
        elif result.any_success:
            title = "⚠️ Partial Registration"
            color = COLOR_WARNING
        else:
            title = "❌ Registration Failed"
            color = COLOR_ERROR

        embed = discord.Embed(title=title, color=color)

        # Add username field
        embed.add_field(
            name="Username",
            value=f"`{result.username}`",
            inline=True,
        )

        # Add email field
        embed.add_field(
            name="Email",
            value=f"`{result.email}`",
            inline=True,
        )

        # Add password field (only if any registration succeeded)
        if result.any_success:
            embed.add_field(
                name="🔑 Password",
                value=f"||`{result.password}`||\n*(Click to reveal)*",
                inline=False,
            )

        # Add services status
        services_text = []
        for sr in result.services:
            if sr.success and not sr.already_existed:
                status = "✅"
                text = f"{status} **{sr.service_name}** - Registered"
            elif sr.already_existed:
                status = "ℹ️"
                text = f"{status} **{sr.service_name}** - Already exists"
            else:
                status = "❌"
                text = f"{status} **{sr.service_name}** - Failed"
                if sr.error:
                    text += (
                        f"\n   └ `{sr.error[:50]}...`"
                        if len(sr.error) > 50
                        else f"\n   └ `{sr.error}`"
                    )
            services_text.append(text)

        embed.add_field(
            name="Services",
            value="\n".join(services_text) or "No services configured",
            inline=False,
        )

        # Add footer with security reminder
        if result.any_success:
            embed.set_footer(text="⚠️ Save this password! It won't be shown again.")

        return embed

    def _create_error_embed(self, error_message: str) -> discord.Embed:
        """
        Create an error embed.

        Args:
            error_message: The error message to display.

        Returns:
            Discord embed with error.
        """
        embed = discord.Embed(
            title="❌ Registration Error",
            description=error_message,
            color=COLOR_ERROR,
        )
        return embed

    def _create_password_reset_embed(
        self, result: PasswordResetResult
    ) -> discord.Embed:
        """
        Create an embed displaying password reset results.

        Args:
            result: The password reset result to display.

        Returns:
            Discord embed with results.
        """
        # Determine overall status
        if result.all_success:
            title = "🔑 Password Reset Complete!"
            color = COLOR_SUCCESS
        elif result.any_success:
            title = "⚠️ Partial Password Reset"
            color = COLOR_WARNING
        else:
            title = "❌ Password Reset Failed"
            color = COLOR_ERROR

        embed = discord.Embed(title=title, color=color)

        # Add username field
        embed.add_field(
            name="Username",
            value=f"`{result.username}`",
            inline=True,
        )

        # Add password field (only if any reset succeeded)
        if result.any_success:
            embed.add_field(
                name="🔑 New Password",
                value=f"||`{result.password}`||\n*(Click to reveal)*",
                inline=False,
            )

        # Add services status
        services_text = []
        for sr in result.services:
            if sr.success:
                status = "✅"
                text = f"{status} **{sr.service_name}** - Password updated"
            else:
                status = "❌"
                text = f"{status} **{sr.service_name}** - {sr.message}"
                if sr.error and sr.error != sr.message:
                    error_msg = (
                        sr.error[:50] + "..." if len(sr.error) > 50 else sr.error
                    )
                    text += f"\n   └ `{error_msg}`"
            services_text.append(text)

        embed.add_field(
            name="Services",
            value="\n".join(services_text) or "No services configured",
            inline=False,
        )

        # Add footer with security reminder
        if result.any_success:
            embed.set_footer(text="⚠️ Save this password! It won't be shown again.")

        return embed

    def _get_services_with_urls(self) -> list[str]:
        """
        Build a list of enabled services and their first URL for the help embed.

        Returns:
            List of formatted lines, e.g. "• [Jellyfin](http://...)" or
            "• **Minecraft — Survival**: `host:port`". Empty if no services.
        """
        lines: list[str] = []
        cfg = self.bot.config

        if (
            getattr(cfg, "jellyfin", None)
            and cfg.jellyfin.enabled
            and cfg.jellyfin.urls
        ):
            url = cfg.jellyfin.urls[0]
            line = f"• [Jellyfin]({url})"
            if (
                getattr(cfg.jellyfin, "description", None)
                and cfg.jellyfin.description.strip()
            ):
                line += f" — {cfg.jellyfin.description.strip()}"
            lines.append(line)

        if (
            getattr(cfg, "minecraft", None)
            and cfg.minecraft.enabled
            and cfg.minecraft.servers
        ):
            for server in cfg.minecraft.servers:
                if server.urls:
                    addr = server.urls[0]
                    line = f"• **Minecraft — {server.name}**: `{addr}`"
                    if (
                        getattr(server, "description", None)
                        and server.description.strip()
                    ):
                        line += f" — {server.description.strip()}"
                    lines.append(line)

        if (
            getattr(cfg, "nextcloud", None)
            and cfg.nextcloud.enabled
            and cfg.nextcloud.urls
        ):
            url = cfg.nextcloud.urls[0]
            line = f"• [NextCloud]({url})"
            if (
                getattr(cfg.nextcloud, "description", None)
                and cfg.nextcloud.description.strip()
            ):
                line += f" — {cfg.nextcloud.description.strip()}"
            lines.append(line)

        if (
            getattr(cfg, "navidrome", None)
            and cfg.navidrome.enabled
            and cfg.navidrome.urls
        ):
            url = cfg.navidrome.urls[0]
            line = f"• [Navidrome]({url})"
            if (
                getattr(cfg.navidrome, "description", None)
                and cfg.navidrome.description.strip()
            ):
                line += f" — {cfg.navidrome.description.strip()}"
            lines.append(line)

        if (
            getattr(cfg, "organizr", None)
            and cfg.organizr.enabled
            and cfg.organizr.urls
        ):
            url = cfg.organizr.urls[0]
            line = f"• [Organizr]({url})"
            if (
                getattr(cfg.organizr, "description", None)
                and cfg.organizr.description.strip()
            ):
                line += f" — {cfg.organizr.description.strip()}"
            lines.append(line)

        if getattr(cfg, "romm", None) and cfg.romm.enabled and cfg.romm.urls:
            url = cfg.romm.urls[0]
            line = f"• [Romm]({url})"
            if getattr(cfg.romm, "description", None) and cfg.romm.description.strip():
                line += f" — {cfg.romm.description.strip()}"
            lines.append(line)

        # Additional name/URL pairs from config (optional description)
        for link in getattr(cfg, "additional_links", []) or []:
            line = f"• [{link.name}]({link.url})"
            if getattr(link, "description", None) and link.description.strip():
                line += f" — {link.description.strip()}"
            lines.append(line)

        return lines

    def _create_full_help_embed(self) -> discord.Embed:
        """
        Create a comprehensive help embed listing all available commands.

        Returns:
            Discord embed with all commands and their descriptions.
        """
        embed = discord.Embed(
            title="📚 MonolithBot Help",
            description=(
                "Welcome! Here are all the commands you can use.\n"
                "All commands work via DM or with `/` slash commands."
            ),
            color=COLOR_INFO,
        )

        # Registration commands
        embed.add_field(
            name="📝 Registration",
            value=(
                "**`/register <username> <email> [password]`**\n"
                "Register for accounts on all Monolith services.\n"
                "• `username` - Your desired username (3-32 chars)\n"
                "• `email` - Your email address\n"
                "• `password` - Optional, auto-generated if not provided\n"
                "\n"
                "*Or DM:* `register <username> <email> [password]`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔑 Password Reset",
            value=(
                "**`/resetpassword [password]`**\n"
                "Reset your password on all services.\n"
                "• `password` - Optional new password\n"
                "• Must be used in DMs for security\n"
                "• Only works if you're already registered"
            ),
            inline=False,
        )

        embed.add_field(
            name="❓ Help",
            value=("**`/help`**\nShows this help message (sent via DM)."),
            inline=False,
        )

        # Show available services with first URL for each
        service_lines = self._get_services_with_urls()
        if service_lines:
            embed.add_field(
                name="🌐 Available Services",
                value="\n".join(service_lines),
                inline=False,
            )

        # Tips
        embed.add_field(
            name="💡 Tips",
            value=(
                "• Passwords are only shown once - save them!\n"
                "• Use spoiler tags to reveal passwords: ||click||\n"
                "• Registration commands work best in DMs"
            ),
            inline=True,
        )

        embed.set_footer(text="Need more help? Contact an administrator.")

        return embed

    def _create_not_registered_embed(self) -> discord.Embed:
        """
        Create an embed for when a Discord user is not registered.

        Returns:
            Discord embed with error.
        """
        embed = discord.Embed(
            title="❌ Not Registered",
            description=(
                "You haven't registered yet.\n\n"
                "Use `/register` or DM me with `register <username> <email>` "
                "to create your accounts first."
            ),
            color=COLOR_ERROR,
        )
        return embed

    def _create_already_registered_embed(self, existing_username: str) -> discord.Embed:
        """
        Create an embed for when a Discord user is already registered.

        Args:
            existing_username: The username they previously registered with.

        Returns:
            Discord embed with error.
        """
        embed = discord.Embed(
            title="ℹ️ Already Registered",
            description=(
                f"You have already registered with the username `{existing_username}`.\n\n"
                "If you need to reset your password, use `/resetpassword` in a DM with me."
            ),
            color=COLOR_INFO,
        )
        return embed

    def _create_username_taken_embed(self, username: str) -> discord.Embed:
        """
        Create an embed for when a username is already taken.

        Args:
            username: The username that's taken.

        Returns:
            Discord embed with error.
        """
        embed = discord.Embed(
            title="❌ Username Taken",
            description=(
                f"The username `{username}` is already registered by another user.\n\n"
                "Please try a different username."
            ),
            color=COLOR_ERROR,
        )
        return embed

    def _create_help_embed(self) -> discord.Embed:
        """
        Create a help embed explaining how to register.

        Returns:
            Discord embed with usage instructions.
        """
        embed = discord.Embed(
            title="📝 User Registration",
            description=(
                "Register for an account on Monolith services.\n\n"
                "This will create accounts for you on all available services "
                "with a single password."
            ),
            color=COLOR_INFO,
        )

        embed.add_field(
            name="Usage",
            value="`register <username> <email> [password]`",
            inline=False,
        )

        embed.add_field(
            name="Examples",
            value=(
                "`register johndoe john@example.com`\n"
                "`register johndoe john@example.com MySecurePass123`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Username Requirements",
            value=(
                "• 3-32 characters\n"
                "• Letters, numbers, underscores, hyphens\n"
                "• Must start with letter or number"
            ),
            inline=True,
        )

        embed.add_field(
            name="Password",
            value=(
                "• Optional - a secure one is generated if not provided\n"
                "• Shown only once after registration"
            ),
            inline=True,
        )

        # Show available services
        if self.registration_service:
            services = self.registration_service.enabled_services
            if services:
                embed.add_field(
                    name="Available Services",
                    value="\n".join(f"• {s}" for s in services),
                    inline=False,
                )

        return embed

    # -------------------------------------------------------------------------
    # Response Helpers
    # -------------------------------------------------------------------------

    async def _send_help(self, channel: discord.DMChannel) -> None:
        """Send the help embed to a channel."""
        embed = self._create_help_embed()
        await channel.send(embed=embed)

    async def _send_usage_error(self, channel: discord.DMChannel) -> None:
        """Send a usage error message."""
        embed = discord.Embed(
            title="❌ Invalid Format",
            description="Please provide both username and email.",
            color=COLOR_ERROR,
        )
        embed.add_field(
            name="Correct Usage",
            value="`register <username> <email>`",
            inline=False,
        )
        embed.add_field(
            name="Example",
            value="`register johndoe john@example.com`",
            inline=False,
        )
        await channel.send(embed=embed)

    async def _send_validation_error(
        self, channel: discord.DMChannel, error: str
    ) -> None:
        """Send a validation error message."""
        embed = self._create_error_embed(error)
        await channel.send(embed=embed)

    async def _send_error(self, channel: discord.DMChannel, error: str) -> None:
        """Send a general error message."""
        embed = self._create_error_embed(error)
        await channel.send(embed=embed)

    async def _send_already_registered_error(
        self, channel: discord.DMChannel, existing_username: str
    ) -> None:
        """Send an error message for already registered users."""
        embed = self._create_already_registered_embed(existing_username)
        await channel.send(embed=embed)

    async def _send_username_taken_error(
        self, channel: discord.DMChannel, username: str
    ) -> None:
        """Send an error message for taken usernames."""
        embed = self._create_username_taken_embed(username)
        await channel.send(embed=embed)

    async def _send_result_embed(
        self, channel: discord.DMChannel, result: RegistrationResult
    ) -> None:
        """Send the registration result embed."""
        embed = self._create_result_embed(result)
        await channel.send(embed=embed)


async def setup(bot: "MonolithBot") -> None:
    """
    Set up the Registration cog.

    This function is called by discord.py when loading the cog.

    Args:
        bot: The MonolithBot instance.
    """
    await bot.add_cog(RegistrationCog(bot))

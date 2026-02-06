from __future__ import annotations

"""
Registration DM handler cog for MonolithBot.

This cog handles direct message interactions for user registration across
multiple services (Jellyfin, NextCloud, Navidrome, Romm).

Key Features:
    - DM-based registration flow
    - Username and email validation
    - Rich embed responses with registration results
    - Password delivered securely via DM only
    - Persistent tracking of Discord user to service account mappings

Usage Flow:
    1. User DMs the bot: "register myusername myemail@example.com"
    2. Bot checks if user already registered (via UserRegistry)
    3. Bot validates input and creates accounts on all enabled services
    4. Bot saves the mapping and responds with registration results

Commands:
    - register <username> <email>: Register on all services
    - /register: Slash command version

Configuration:
    Requires `registration.enabled = true` in config.
    At least one service (Jellyfin, NextCloud, Navidrome, Romm) must be enabled.

See Also:
    - bot.services.registration: Registration orchestrator
    - bot.services.user_registry: User mapping persistence
    - bot.config: Registration and service configuration
"""

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

        # Parse username and email
        parts = args.split()

        if len(parts) < 2:
            await self._send_usage_error(message.channel)
            return

        username = parts[0]
        email = parts[1]

        # Process the registration
        await self._process_registration(message.channel, message.author, username, email)

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
    )
    async def register_command(
        self,
        interaction: discord.Interaction,
        username: str,
        email: str,
    ) -> None:
        """
        Slash command for user registration.

        This command can be used in DMs or guilds, but the password
        will only be shown in DMs for security.

        Args:
            interaction: The Discord interaction.
            username: Desired username.
            email: User's email address.
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
            await interaction.followup.send(
                "🔒 For security, please use this command in a DM with me.\n"
                f"Send me a DM with: `register {username} {email}`",
                ephemeral=True,
            )
            return

        # Process registration
        await self._process_registration_interaction(interaction, username, email)

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
    ) -> None:
        """
        Process a registration request from a DM message.

        Args:
            channel: The DM channel to respond in.
            user: The Discord user requesting registration.
            username: Desired username.
            email: User's email address.
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

        # Check if Discord user already registered
        if self.user_registry and self.user_registry.is_discord_user_registered(user.id):
            existing = self.user_registry.get_by_discord_id(user.id)
            await self._send_already_registered_error(channel, existing.username)
            return

        # Check if username is already taken
        if self.user_registry and self.user_registry.is_username_taken(username):
            await self._send_username_taken_error(channel, username)
            return

        # Show typing indicator while processing
        async with channel.typing():
            # Perform registration
            try:
                result = await self.registration_service.register_user(username, email)
            except Exception as e:
                logger.error(f"Registration failed for {username}: {e}")
                await self._send_error(channel, "An unexpected error occurred during registration.")
                return

        # Save to registry if any registration succeeded
        if result.any_success and self.user_registry:
            successful_services = [
                sr.service_name for sr in result.services
                if sr.success and not sr.already_existed
            ]
            # Include services where user already existed (they're still "registered")
            all_registered = [sr.service_name for sr in result.services if sr.success]

            self.user_registry.add_user(
                discord_id=user.id,
                discord_name=str(user),
                username=username,
                email=email,
                services=all_registered,
            )
            await self.user_registry.save()
            logger.info(f"Saved registration to registry: {user} -> {username}")

        # Send result embed
        await self._send_result_embed(channel, result)

    async def _process_registration_interaction(
        self,
        interaction: discord.Interaction,
        username: str,
        email: str,
    ) -> None:
        """
        Process a registration request from a slash command.

        Args:
            interaction: The Discord interaction.
            username: Desired username.
            email: User's email address.
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

        # Check if Discord user already registered
        if self.user_registry and self.user_registry.is_discord_user_registered(user.id):
            existing = self.user_registry.get_by_discord_id(user.id)
            await interaction.followup.send(
                embed=self._create_already_registered_embed(existing.username),
                ephemeral=True,
            )
            return

        # Check if username is already taken
        if self.user_registry and self.user_registry.is_username_taken(username):
            await interaction.followup.send(
                embed=self._create_username_taken_embed(username),
                ephemeral=True,
            )
            return

        # Perform registration
        try:
            result = await self.registration_service.register_user(username, email)
        except Exception as e:
            logger.error(f"Registration failed for {username}: {e}")
            await interaction.followup.send(
                embed=self._create_error_embed("An unexpected error occurred during registration."),
                ephemeral=True,
            )
            return

        # Save to registry if any registration succeeded
        if result.any_success and self.user_registry:
            all_registered = [sr.service_name for sr in result.services if sr.success]

            self.user_registry.add_user(
                discord_id=user.id,
                discord_name=str(user),
                username=username,
                email=email,
                services=all_registered,
            )
            await self.user_registry.save()
            logger.info(f"Saved registration to registry: {user} -> {username}")

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
                embed=self._create_error_embed("An unexpected error occurred during password reset."),
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
                    text += f"\n   └ `{sr.error[:50]}...`" if len(sr.error) > 50 else f"\n   └ `{sr.error}`"
            services_text.append(text)

        embed.add_field(
            name="Services",
            value="\n".join(services_text) or "No services configured",
            inline=False,
        )

        # Add footer with security reminder
        if result.any_success:
            embed.set_footer(
                text="⚠️ Save this password! It won't be shown again."
            )

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

    def _create_password_reset_embed(self, result: PasswordResetResult) -> discord.Embed:
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
                    error_msg = sr.error[:50] + "..." if len(sr.error) > 50 else sr.error
                    text += f"\n   └ `{error_msg}`"
            services_text.append(text)

        embed.add_field(
            name="Services",
            value="\n".join(services_text) or "No services configured",
            inline=False,
        )

        # Add footer with security reminder
        if result.any_success:
            embed.set_footer(
                text="⚠️ Save this password! It won't be shown again."
            )

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
                "If you need to reset your password or update your account, "
                "please contact an administrator."
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
            value="`register <username> <email>`",
            inline=False,
        )

        embed.add_field(
            name="Example",
            value="`register johndoe john@example.com`",
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

        # Show available services
        if self.registration_service:
            services = self.registration_service.enabled_services
            if services:
                embed.add_field(
                    name="Available Services",
                    value="\n".join(f"• {s}" for s in services),
                    inline=True,
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

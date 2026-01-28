"""
Configuration loader for MonolithBot.

This module handles loading and validating configuration from multiple sources,
providing a unified Config object for the rest of the application.

Configuration Sources (in order of precedence):
    1. Environment variables (highest priority) - for Docker/production
    2. JSON config file - for local development

This design allows developers to use a config.json file during development
while production deployments use environment variables without code changes.

Example JSON config (config.json):
    {
        "discord": {
            "token": "BOT_TOKEN",
            "announcement_channel_id": 123456789
        },
        "jellyfin": {
            "url": "http://localhost:8096",
            "api_key": "API_KEY"
        }
    }

Equivalent environment variables:
    DISCORD_TOKEN=BOT_TOKEN
    DISCORD_ANNOUNCEMENT_CHANNEL_ID=123456789
    JELLYFIN_URL=http://localhost:8096
    JELLYFIN_API_KEY=API_KEY

See Also:
    - config.json.example: Full example with all options
    - .env.example: Environment variable reference
    - ARCHITECTURE.md: Configuration system documentation
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# =============================================================================
# Configuration Data Classes
# =============================================================================


@dataclass
class DiscordConfig:
    """
    Discord-related configuration settings.

    Attributes:
        token: Discord bot token from the Developer Portal.
            Keep this secret - never commit to version control.
        announcement_channel_id: Channel ID where new content announcements
            will be posted.
        alert_channel_id: Channel ID for server status alerts (online/offline).
            Defaults to announcement_channel_id if not specified.
    """

    token: str
    announcement_channel_id: int
    alert_channel_id: Optional[int] = None

    def __post_init__(self) -> None:
        """Set alert_channel_id to announcement_channel_id if not provided."""
        if self.alert_channel_id is None:
            self.alert_channel_id = self.announcement_channel_id


@dataclass
class JellyfinConfig:
    """
    Jellyfin server configuration settings.

    Attributes:
        url: Base URL of the Jellyfin server (e.g., "http://localhost:8096").
            Trailing slashes are automatically removed.
        api_key: Jellyfin API key for authentication.
            Generate this in Jellyfin Dashboard → API Keys.
    """

    url: str
    api_key: str

    def __post_init__(self) -> None:
        """Normalize the URL by removing trailing slashes."""
        self.url = self.url.rstrip("/")


@dataclass
class ScheduleConfig:
    """
    Scheduling configuration for announcements, suggestions, and health checks.

    Attributes:
        announcement_times: List of times to announce new content in HH:MM format
            (24-hour). Example: ["09:00", "17:00", "21:00"]
        suggestion_times: List of times to post random suggestions in HH:MM format
            (24-hour). Example: ["12:00", "20:00"]
        timezone: IANA timezone name for interpreting announcement times.
            Example: "America/Los_Angeles", "Europe/London", "UTC"
        health_check_interval_minutes: How often to check if Jellyfin is online.
            Lower values detect outages faster but increase API calls.
        lookback_hours: How far back to look for "new" content when announcing.
            Content added within this many hours is considered new.
        max_items_per_type: Maximum number of items to show per content type
            in announcements. Prevents flooding the channel with too many embeds.
    """

    announcement_times: list[str] = field(default_factory=lambda: ["17:00"])
    suggestion_times: list[str] = field(default_factory=list)
    timezone: str = "America/Los_Angeles"
    health_check_interval_minutes: int = 5
    lookback_hours: int = 24
    max_items_per_type: int = 10


@dataclass
class Config:
    """
    Main configuration container aggregating all settings.

    This is the primary configuration object passed throughout the application.
    Access nested settings via attributes: config.discord.token, config.jellyfin.url, etc.

    Attributes:
        discord: Discord bot and channel settings.
        jellyfin: Jellyfin server connection settings.
        schedule: Timing settings for announcements and health checks.
        content_types: List of Jellyfin content types to announce.
            Valid values: "Movie", "Series", "Audio", "Episode"

    Example:
        >>> config = load_config(Path("config.json"))
        >>> print(config.jellyfin.url)
        'http://localhost:8096'
        >>> print(config.schedule.announcement_times)
        ['17:00']
    """

    discord: DiscordConfig
    jellyfin: JellyfinConfig
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    content_types: list[str] = field(
        default_factory=lambda: ["Movie", "Series", "Audio"]
    )


# =============================================================================
# Exceptions
# =============================================================================


class ConfigurationError(Exception):
    """
    Raised when configuration is invalid or missing required values.

    This exception provides user-friendly error messages indicating
    which configuration value is missing and how to provide it.

    Example:
        >>> raise ConfigurationError(
        ...     "Discord token is required. Set DISCORD_TOKEN environment "
        ...     "variable or 'discord.token' in config.json"
        ... )
    """

    pass


# =============================================================================
# Environment Variable Helpers
# =============================================================================


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get an environment variable value.

    Args:
        key: Environment variable name.
        default: Value to return if the variable is not set.

    Returns:
        The environment variable value, or default if not set.
    """
    return os.environ.get(key, default)


def _get_env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    """
    Get an environment variable as an integer.

    Args:
        key: Environment variable name.
        default: Value to return if the variable is not set.

    Returns:
        The environment variable value as an integer, or default if not set.

    Raises:
        ConfigurationError: If the value exists but cannot be parsed as an integer.
    """
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(
            f"Environment variable {key} must be an integer, got: {value}"
        )


def _get_env_list(key: str, default: Optional[list[str]] = None) -> Optional[list[str]]:
    """
    Get an environment variable as a comma-separated list.

    Whitespace around items is stripped. Empty items are ignored.

    Args:
        key: Environment variable name.
        default: Value to return if the variable is not set.

    Returns:
        List of strings parsed from the comma-separated value,
        or default if not set.

    Example:
        >>> os.environ["TIMES"] = "09:00, 17:00, 21:00"
        >>> _get_env_list("TIMES")
        ['09:00', '17:00', '21:00']
    """
    value = os.environ.get(key)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# =============================================================================
# Configuration Building Functions
# =============================================================================


def _load_json_config(config_path: Path) -> dict[str, Any]:
    """
    Load configuration from a JSON file.

    Args:
        config_path: Path to the JSON configuration file.

    Returns:
        Dictionary containing the parsed JSON configuration.
        Returns an empty dict if the file doesn't exist (allowing
        environment-only configuration).

    Raises:
        ConfigurationError: If the file exists but contains invalid JSON.
    """
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in config file: {e}")


def _build_discord_config(json_config: dict[str, Any]) -> DiscordConfig:
    """
    Build Discord configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated DiscordConfig object.

    Raises:
        ConfigurationError: If required values (token, announcement_channel_id)
            are not provided in either source.

    Environment Variables:
        - DISCORD_TOKEN: Bot token
        - DISCORD_ANNOUNCEMENT_CHANNEL_ID: Announcement channel ID
        - DISCORD_ALERT_CHANNEL_ID: Alert channel ID (optional)
    """
    discord_json = json_config.get("discord", {})

    # Token is required
    token = _get_env("DISCORD_TOKEN") or discord_json.get("token")
    if not token:
        raise ConfigurationError(
            "Discord token is required. Set DISCORD_TOKEN environment variable "
            "or 'discord.token' in config.json"
        )

    # Announcement channel ID is required
    announcement_channel_id = _get_env_int(
        "DISCORD_ANNOUNCEMENT_CHANNEL_ID"
    ) or discord_json.get("announcement_channel_id")
    if not announcement_channel_id:
        raise ConfigurationError(
            "Discord announcement channel ID is required. Set "
            "DISCORD_ANNOUNCEMENT_CHANNEL_ID environment variable or "
            "'discord.announcement_channel_id' in config.json"
        )

    # Alert channel ID is optional (defaults to announcement channel)
    alert_channel_id = _get_env_int("DISCORD_ALERT_CHANNEL_ID") or discord_json.get(
        "alert_channel_id"
    )

    return DiscordConfig(
        token=token,
        announcement_channel_id=announcement_channel_id,
        alert_channel_id=alert_channel_id,
    )


def _build_jellyfin_config(json_config: dict[str, Any]) -> JellyfinConfig:
    """
    Build Jellyfin configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated JellyfinConfig object.

    Raises:
        ConfigurationError: If required values (url, api_key) are not
            provided in either source.

    Environment Variables:
        - JELLYFIN_URL: Server base URL
        - JELLYFIN_API_KEY: API key for authentication
    """
    jellyfin_json = json_config.get("jellyfin", {})

    # URL is required
    url = _get_env("JELLYFIN_URL") or jellyfin_json.get("url")
    if not url:
        raise ConfigurationError(
            "Jellyfin URL is required. Set JELLYFIN_URL environment variable "
            "or 'jellyfin.url' in config.json"
        )

    # API key is required
    api_key = _get_env("JELLYFIN_API_KEY") or jellyfin_json.get("api_key")
    if not api_key:
        raise ConfigurationError(
            "Jellyfin API key is required. Set JELLYFIN_API_KEY environment "
            "variable or 'jellyfin.api_key' in config.json"
        )

    return JellyfinConfig(url=url, api_key=api_key)


def _build_schedule_config(json_config: dict[str, Any]) -> ScheduleConfig:
    """
    Build schedule configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.
    All schedule settings have sensible defaults.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated ScheduleConfig object.

    Environment Variables:
        - SCHEDULE_ANNOUNCEMENT_TIMES: Comma-separated times (e.g., "09:00,17:00")
        - SCHEDULE_SUGGESTION_TIMES: Comma-separated times (e.g., "12:00,20:00")
        - SCHEDULE_TIMEZONE: IANA timezone name
        - SCHEDULE_HEALTH_CHECK_INTERVAL: Minutes between health checks
        - SCHEDULE_LOOKBACK_HOURS: Hours to look back for new content
    """
    schedule_json = json_config.get("schedule", {})

    announcement_times = _get_env_list(
        "SCHEDULE_ANNOUNCEMENT_TIMES"
    ) or schedule_json.get("announcement_times", ["17:00"])

    suggestion_times = _get_env_list(
        "SCHEDULE_SUGGESTION_TIMES"
    ) or schedule_json.get("suggestion_times", [])

    timezone = _get_env("SCHEDULE_TIMEZONE") or schedule_json.get(
        "timezone", "America/Los_Angeles"
    )

    health_check_interval = _get_env_int(
        "SCHEDULE_HEALTH_CHECK_INTERVAL"
    ) or schedule_json.get("health_check_interval_minutes", 5)

    lookback_hours = _get_env_int("SCHEDULE_LOOKBACK_HOURS") or schedule_json.get(
        "lookback_hours", 24
    )

    max_items_per_type = _get_env_int(
        "SCHEDULE_MAX_ITEMS_PER_TYPE"
    ) or schedule_json.get("max_items_per_type", 10)

    return ScheduleConfig(
        announcement_times=announcement_times,
        suggestion_times=suggestion_times,
        timezone=timezone,
        health_check_interval_minutes=health_check_interval,
        lookback_hours=lookback_hours,
        max_items_per_type=max_items_per_type,
    )


# =============================================================================
# Public API
# =============================================================================


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load and validate configuration from JSON file and environment variables.

    This is the main entry point for configuration loading. It combines
    settings from a JSON file (if present) with environment variables,
    where environment variables take precedence.

    Args:
        config_path: Path to JSON config file. Defaults to 'config.json'
            in the current working directory. The file is optional if all
            required settings are provided via environment variables.

    Returns:
        Fully populated and validated Config object.

    Raises:
        ConfigurationError: If required configuration is missing or invalid.
            The error message indicates which value is missing and how to
            provide it.

    Example:
        >>> # Load from default config.json
        >>> config = load_config()

        >>> # Load from custom path
        >>> config = load_config(Path("/etc/monolithbot/config.json"))

        >>> # Access configuration values
        >>> print(config.discord.token)
        >>> print(config.jellyfin.url)
        >>> print(config.schedule.announcement_times)
    """
    if config_path is None:
        config_path = Path("config.json")

    # Load JSON config (returns empty dict if file doesn't exist)
    json_config = _load_json_config(config_path)

    # Build each configuration section
    discord_config = _build_discord_config(json_config)
    jellyfin_config = _build_jellyfin_config(json_config)
    schedule_config = _build_schedule_config(json_config)

    # Content types with env var override
    content_types = _get_env_list("CONTENT_TYPES") or json_config.get(
        "content_types", ["Movie", "Series", "Audio"]
    )

    return Config(
        discord=discord_config,
        jellyfin=jellyfin_config,
        schedule=schedule_config,
        content_types=content_types,
    )

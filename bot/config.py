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
            "enabled": true,
            "urls": [
                "http://jellyfin.mydomain.com:8096",
                "http://jellyfin.local:8096",
                "http://192.168.1.100:8096"
            ],
            "api_key": "API_KEY",
            "content_types": ["Movie", "Series", "Audio"],
            "schedule": {
                "announcement_times": ["17:00"],
                "suggestion_times": ["12:00", "20:00"],
                "timezone": "America/Los_Angeles",
                "health_check_interval_minutes": 5,
                "lookback_hours": 24,
                "max_items_per_type": 10
            }
        }
    }

Equivalent environment variables:
    DISCORD_TOKEN=BOT_TOKEN
    DISCORD_ANNOUNCEMENT_CHANNEL_ID=123456789
    JELLYFIN_ENABLED=true
    JELLYFIN_URL=http://primary:8096,http://secondary:8096,http://192.168.1.100:8096
    JELLYFIN_API_KEY=API_KEY
    JELLYFIN_CONTENT_TYPES=Movie,Series,Audio
    JELLYFIN_SCHEDULE_ANNOUNCEMENT_TIMES=17:00
    JELLYFIN_SCHEDULE_TIMEZONE=America/Los_Angeles

Note: Jellyfin URLs support multiple values for failover. The bot will try each URL
in order during health checks and use the first working one for API calls.
Single URL strings are still supported for backward compatibility.

See Also:
    - config.json.example: Full example with all options
    - .env.example: Environment variable reference
    - ARCHITECTURE.md: Configuration system documentation
"""

from __future__ import annotations  # Enable PEP 604 style type hints for Python 3.8+

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
class JellyfinScheduleConfig:
    """
    Scheduling configuration for Jellyfin-specific tasks.

    Attributes:
        announcement_times: List of times to announce new content in HH:MM format
            (24-hour). Example: ["09:00", "17:00", "21:00"]
        suggestion_times: List of times to post random suggestions in HH:MM format
            (24-hour). Example: ["12:00", "20:00"]
        timezone: IANA timezone name for interpreting times.
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
class JellyfinConfig:
    """
    Jellyfin server configuration settings.

    Attributes:
        enabled: Whether Jellyfin integration is enabled.
        urls: List of Jellyfin server URLs to try in order (for failover).
            Each URL should be a base URL like "http://localhost:8096".
            Trailing slashes are automatically removed.
            During health checks, URLs are tried in order until one works.
        api_key: Jellyfin API key for authentication.
            Generate this in Jellyfin Dashboard → API Keys.
        content_types: List of Jellyfin content types to announce.
            Valid values: "Movie", "Series", "Audio", "Episode"
        schedule: Scheduling settings for Jellyfin-specific tasks.
        description: Optional short description shown next to the link in /help.
    """

    enabled: bool
    urls: list[str]
    api_key: str
    description: str = ""
    content_types: list[str] = field(
        default_factory=lambda: ["Movie", "Series", "Audio"]
    )
    schedule: JellyfinScheduleConfig = field(default_factory=JellyfinScheduleConfig)

    def __post_init__(self) -> None:
        """Normalize all URLs by removing trailing slashes."""
        self.urls = [url.rstrip("/") for url in self.urls]

    @property
    def url(self) -> str:
        """Get the primary (first) URL for backward compatibility.

        Note: For actual API calls, use JellyfinService which handles
        URL failover. This property is mainly for logging/display.
        """
        return self.urls[0] if self.urls else ""


@dataclass
class MinecraftScheduleConfig:
    """
    Scheduling configuration for Minecraft-specific tasks.

    Attributes:
        timezone: IANA timezone name for interpreting times.
            Example: "America/Los_Angeles", "Europe/London", "UTC"
        health_check_interval_minutes: How often to check if servers are online.
            Lower values detect outages faster but increase network traffic.
        player_check_interval_seconds: How often to poll for player changes.
            Used for detecting player joins. Lower values = faster announcements
            but more frequent queries.
    """

    timezone: str = "America/Los_Angeles"
    health_check_interval_minutes: int = 1
    player_check_interval_seconds: int = 30


@dataclass
class MinecraftServerConfig:
    """
    Configuration for a single Minecraft server instance.

    Attributes:
        name: Display name for this server (e.g., "Survival", "Creative").
            Used in Discord notifications to identify which server.
        urls: List of server addresses to try in order (for failover).
            Each should be in "host:port" or "host" format (default port 25565).
            During health checks, URLs are tried in order until one works.
        description: Optional short description shown next to the server in /help.
    """

    name: str
    urls: list[str]
    description: str = ""

    def __post_init__(self) -> None:
        """Validate server configuration."""
        if not self.name:
            raise ValueError("Minecraft server name cannot be empty")
        if not self.urls:
            raise ValueError(
                f"Minecraft server '{self.name}' must have at least one URL"
            )


@dataclass
class MinecraftConfig:
    """
    Minecraft server monitoring configuration settings.

    Attributes:
        enabled: Whether Minecraft integration is enabled.
        announcement_channel_id: Channel ID for player join announcements.
        alert_channel_id: Channel ID for server status alerts (online/offline).
            Defaults to announcement_channel_id if not specified.
        servers: List of Minecraft server instances to monitor.
            Each server can have multiple URLs for failover.
        schedule: Scheduling settings for Minecraft-specific tasks.
    """

    enabled: bool
    announcement_channel_id: Optional[int] = None
    alert_channel_id: Optional[int] = None
    servers: list[MinecraftServerConfig] = field(default_factory=list)
    schedule: MinecraftScheduleConfig = field(default_factory=MinecraftScheduleConfig)

    def __post_init__(self) -> None:
        """Set alert_channel_id to announcement_channel_id if not provided."""
        if self.alert_channel_id is None:
            self.alert_channel_id = self.announcement_channel_id


@dataclass
class NextCloudConfig:
    """
    NextCloud server configuration for user provisioning.

    Uses the NextCloud OCS Provisioning API for user management.
    Requires admin credentials with user provisioning permissions.

    Attributes:
        enabled: Whether NextCloud integration is enabled.
        urls: List of NextCloud server URLs to try in order (for failover).
            Each URL should be the base URL like "https://nextcloud.example.com".
        admin_user: Admin username for OCS API authentication.
        admin_password: Admin password for OCS API authentication.
        description: Optional short description shown next to the link in /help.

    See Also:
        - NextCloud OCS API: https://docs.nextcloud.com/server/latest/admin_manual/
    """

    enabled: bool
    urls: list[str] = field(default_factory=list)
    admin_user: str = ""
    admin_password: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Normalize all URLs by removing trailing slashes."""
        self.urls = [url.rstrip("/") for url in self.urls]

    @property
    def url(self) -> str:
        """Get the primary (first) URL for backward compatibility."""
        return self.urls[0] if self.urls else ""


@dataclass
class NavidromeConfig:
    """
    Navidrome server configuration for user provisioning.

    Uses the Navidrome REST API for user management.
    Requires admin credentials with user management permissions.

    Attributes:
        enabled: Whether Navidrome integration is enabled.
        urls: List of Navidrome server URLs to try in order (for failover).
            Each URL should be the base URL like "https://navidrome.example.com".
        admin_user: Admin username for API authentication.
        admin_password: Admin password for API authentication.
        description: Optional short description shown next to the link in /help.

    See Also:
        - Navidrome API documentation
    """

    enabled: bool
    urls: list[str] = field(default_factory=list)
    admin_user: str = ""
    admin_password: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Normalize all URLs by removing trailing slashes."""
        self.urls = [url.rstrip("/") for url in self.urls]

    @property
    def url(self) -> str:
        """Get the primary (first) URL for backward compatibility."""
        return self.urls[0] if self.urls else ""


@dataclass
class OrganizrConfig:
    """
    Organizr server configuration for user provisioning.

    Uses the Organizr v2 REST API for user management.
    Requires admin credentials (session cookie after login).

    Attributes:
        enabled: Whether Organizr integration is enabled.
        urls: List of Organizr server URLs to try in order (for failover).
            Each URL should be the base URL like "https://organizr.example.com".
        admin_user: Admin username for API authentication.
        admin_password: Admin password for API authentication.
        description: Optional short description shown next to the link in /help.

    See Also:
        - Organizr GitHub: https://github.com/causefx/Organizr
    """

    enabled: bool = False
    urls: list[str] = field(default_factory=list)
    admin_user: str = ""
    admin_password: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Normalize all URLs by removing trailing slashes."""
        self.urls = [url.rstrip("/") for url in self.urls]

    @property
    def url(self) -> str:
        """Get the primary (first) URL for backward compatibility."""
        return self.urls[0] if self.urls else ""


@dataclass
class RommConfig:
    """
    Romm server configuration for user provisioning.

    Uses the Romm REST API for user management.
    Requires admin credentials or API key with user management permissions.

    Attributes:
        enabled: Whether Romm integration is enabled.
        urls: List of Romm server URLs to try in order (for failover).
            Each URL should be the base URL like "https://romm.example.com".
        admin_user: Admin username for API authentication.
        admin_password: Admin password for API authentication.
        description: Optional short description shown next to the link in /help.

    See Also:
        - Romm GitHub: https://github.com/rommapp/romm
    """

    enabled: bool
    urls: list[str] = field(default_factory=list)
    admin_user: str = ""
    admin_password: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Normalize all URLs by removing trailing slashes."""
        self.urls = [url.rstrip("/") for url in self.urls]

    @property
    def url(self) -> str:
        """Get the primary (first) URL for backward compatibility."""
        return self.urls[0] if self.urls else ""


@dataclass
class RegistrationConfig:
    """
    Configuration for the multi-service user registration feature.

    When enabled, users can DM the bot with a username and email to
    automatically create accounts on all enabled services.

    Attributes:
        enabled: Whether the registration feature is enabled.
            Requires at least one service (Jellyfin, NextCloud, Navidrome, Romm)
            to also be enabled.
        registry_file: Path to the JSON file storing Discord user to service
            account mappings. Defaults to "data/user_registry.json".
    """

    enabled: bool = False
    registry_file: str = "data/user_registry.json"


@dataclass
class LoggingConfig:
    """
    Logging configuration settings.

    Controls where logs are written and at what level of detail.

    Attributes:
        log_directory: Directory for log files. Will be created if it doesn't exist.
            In Docker, this should be a mounted volume for persistence.
        log_level: Minimum level to log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_to_console: Whether to also output logs to stdout/stderr.
        log_to_file: Whether to write logs to files in log_directory.
    """

    log_directory: str = "logs"
    log_level: str = "INFO"
    log_to_console: bool = True
    log_to_file: bool = True


@dataclass
class AdditionalLinkConfig:
    """
    A single name/URL pair for the help embed.

    Used by the "additional_links" config section to show arbitrary
    links (e.g. Wiki, Status Page) in the /help command.

    Attributes:
        name: Display name for the link (e.g. "Wiki", "Status").
        url: Full URL (e.g. "https://wiki.example.com").
        description: Optional short description shown next to the link in /help.
    """

    name: str
    url: str
    description: str = ""


@dataclass
class Config:
    """
    Main configuration container aggregating all settings.

    This is the primary configuration object passed throughout the application.
    Access nested settings via attributes: config.discord.token, config.jellyfin.url, etc.

    Attributes:
        discord: Discord bot and channel settings.
        jellyfin: Jellyfin server connection and schedule settings.
        minecraft: Minecraft server monitoring settings.
        nextcloud: NextCloud server connection settings for user provisioning.
        navidrome: Navidrome server connection settings for user provisioning.
        organizr: Organizr server connection settings for user provisioning.
        romm: Romm server connection settings for user provisioning.
        registration: Multi-service user registration feature settings.
        additional_links: Optional list of name/URL pairs shown in /help.
        logging: Logging configuration (directory, level, output targets).

    Example:
        >>> config = load_config(Path("config.json"))
        >>> print(config.jellyfin.url)
        'http://localhost:8096'
        >>> print(config.jellyfin.schedule.announcement_times)
        ['17:00']
        >>> print(config.jellyfin.content_types)
        ['Movie', 'Series', 'Audio']
        >>> print(config.minecraft.servers[0].name)
        'Survival'
        >>> print(config.registration.enabled)
        False
    """

    discord: DiscordConfig
    jellyfin: JellyfinConfig
    minecraft: MinecraftConfig
    nextcloud: NextCloudConfig
    navidrome: NavidromeConfig
    organizr: OrganizrConfig
    romm: RommConfig
    registration: RegistrationConfig
    additional_links: list[AdditionalLinkConfig]
    logging: LoggingConfig


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


def _get_env_bool(key: str, default: Optional[bool] = None) -> Optional[bool]:
    """
    Get an environment variable as a boolean.

    Args:
        key: Environment variable name.
        default: Value to return if the variable is not set.

    Returns:
        The environment variable value as a boolean, or default if not set.
        Recognizes "true", "1", "yes" as True (case-insensitive).
    """
    value = os.environ.get(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


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


def _build_jellyfin_schedule_config(
    schedule_json: dict[str, Any],
) -> JellyfinScheduleConfig:
    """
    Build Jellyfin schedule configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.
    All schedule settings have sensible defaults.

    Args:
        schedule_json: Parsed JSON schedule configuration dictionary.

    Returns:
        Populated JellyfinScheduleConfig object.

    Environment Variables:
        - JELLYFIN_SCHEDULE_ANNOUNCEMENT_TIMES: Comma-separated times
        - JELLYFIN_SCHEDULE_SUGGESTION_TIMES: Comma-separated times
        - JELLYFIN_SCHEDULE_TIMEZONE: IANA timezone name
        - JELLYFIN_SCHEDULE_HEALTH_CHECK_INTERVAL: Minutes between health checks
        - JELLYFIN_SCHEDULE_LOOKBACK_HOURS: Hours to look back for new content
        - JELLYFIN_SCHEDULE_MAX_ITEMS_PER_TYPE: Max items per content type
    """
    announcement_times = _get_env_list(
        "JELLYFIN_SCHEDULE_ANNOUNCEMENT_TIMES"
    ) or schedule_json.get("announcement_times", ["17:00"])

    suggestion_times = _get_env_list(
        "JELLYFIN_SCHEDULE_SUGGESTION_TIMES"
    ) or schedule_json.get("suggestion_times", [])

    timezone = _get_env("JELLYFIN_SCHEDULE_TIMEZONE") or schedule_json.get(
        "timezone", "America/Los_Angeles"
    )

    health_check_interval = _get_env_int(
        "JELLYFIN_SCHEDULE_HEALTH_CHECK_INTERVAL"
    ) or schedule_json.get("health_check_interval_minutes", 5)

    lookback_hours = _get_env_int(
        "JELLYFIN_SCHEDULE_LOOKBACK_HOURS"
    ) or schedule_json.get("lookback_hours", 24)

    max_items_per_type = _get_env_int(
        "JELLYFIN_SCHEDULE_MAX_ITEMS_PER_TYPE"
    ) or schedule_json.get("max_items_per_type", 10)

    return JellyfinScheduleConfig(
        announcement_times=announcement_times,
        suggestion_times=suggestion_times,
        timezone=timezone,
        health_check_interval_minutes=health_check_interval,
        lookback_hours=lookback_hours,
        max_items_per_type=max_items_per_type,
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
        ConfigurationError: If Jellyfin is enabled but required values
            (urls, api_key) are not provided in either source.

    Environment Variables:
        - JELLYFIN_ENABLED: Whether Jellyfin integration is enabled
        - JELLYFIN_URL: Server base URL(s), comma-separated for multiple
        - JELLYFIN_API_KEY: API key for authentication
        - JELLYFIN_CONTENT_TYPES: Comma-separated content types

    JSON supports both single URL and list formats:
        - "url": "http://server:8096" (backward compatible)
        - "urls": ["http://primary:8096", "http://backup:8096"] (new format)
    """
    jellyfin_json = json_config.get("jellyfin", {})

    # Check if enabled (defaults to True for backward compatibility)
    enabled_env = _get_env_bool("JELLYFIN_ENABLED")
    enabled = (
        enabled_env if enabled_env is not None else jellyfin_json.get("enabled", True)
    )

    # URLs: env var takes precedence, supports comma-separated list
    # JSON supports both "url" (string) and "urls" (list) for backward compatibility
    urls_from_env = _get_env_list("JELLYFIN_URL")
    if urls_from_env:
        urls = urls_from_env
    else:
        # Check for "urls" list first, then fall back to "url" string
        urls_from_json = jellyfin_json.get("urls")
        if urls_from_json is not None:
            # "urls" key exists - should be a list
            if isinstance(urls_from_json, list):
                urls = urls_from_json
            else:
                # Handle case where "urls" is accidentally a string
                urls = [urls_from_json]
        else:
            # Fall back to legacy "url" string
            url_from_json = jellyfin_json.get("url")
            if url_from_json:
                urls = (
                    [url_from_json] if isinstance(url_from_json, str) else url_from_json
                )
            else:
                urls = []

    if enabled and not urls:
        raise ConfigurationError(
            "Jellyfin URL is required. Set JELLYFIN_URL environment variable "
            "or 'jellyfin.url' (string) or 'jellyfin.urls' (list) in config.json"
        )

    # API key is required if enabled
    api_key = _get_env("JELLYFIN_API_KEY") or jellyfin_json.get("api_key")
    if enabled and not api_key:
        raise ConfigurationError(
            "Jellyfin API key is required. Set JELLYFIN_API_KEY environment "
            "variable or 'jellyfin.api_key' in config.json"
        )

    # Content types with env var override
    content_types = _get_env_list("JELLYFIN_CONTENT_TYPES") or jellyfin_json.get(
        "content_types", ["Movie", "Series", "Audio"]
    )

    # Build nested schedule config
    schedule_json = jellyfin_json.get("schedule", {})
    schedule_config = _build_jellyfin_schedule_config(schedule_json)

    desc = jellyfin_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return JellyfinConfig(
        enabled=enabled,
        urls=urls or [],
        api_key=api_key or "",
        content_types=content_types,
        schedule=schedule_config,
        description=description,
    )


def _build_minecraft_schedule_config(
    schedule_json: dict[str, Any],
) -> MinecraftScheduleConfig:
    """
    Build Minecraft schedule configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.
    All schedule settings have sensible defaults.

    Args:
        schedule_json: Parsed JSON schedule configuration dictionary.

    Returns:
        Populated MinecraftScheduleConfig object.

    Environment Variables:
        - MINECRAFT_SCHEDULE_TIMEZONE: IANA timezone name
        - MINECRAFT_SCHEDULE_HEALTH_CHECK_INTERVAL: Minutes between health checks
        - MINECRAFT_SCHEDULE_PLAYER_CHECK_INTERVAL: Seconds between player checks
    """
    timezone = _get_env("MINECRAFT_SCHEDULE_TIMEZONE") or schedule_json.get(
        "timezone", "America/Los_Angeles"
    )

    health_check_interval = _get_env_int(
        "MINECRAFT_SCHEDULE_HEALTH_CHECK_INTERVAL"
    ) or schedule_json.get("health_check_interval_minutes", 1)

    player_check_interval = _get_env_int(
        "MINECRAFT_SCHEDULE_PLAYER_CHECK_INTERVAL"
    ) or schedule_json.get("player_check_interval_seconds", 30)

    return MinecraftScheduleConfig(
        timezone=timezone,
        health_check_interval_minutes=health_check_interval,
        player_check_interval_seconds=player_check_interval,
    )


def _build_minecraft_server_config(
    server_json: dict[str, Any],
) -> MinecraftServerConfig:
    """
    Build a single Minecraft server configuration from JSON.

    Args:
        server_json: Dictionary containing server name and urls.

    Returns:
        Populated MinecraftServerConfig object.

    Raises:
        ConfigurationError: If name or urls are missing/invalid.
    """
    name = server_json.get("name")
    if not name:
        raise ConfigurationError("Each Minecraft server must have a 'name' field")

    urls = server_json.get("urls", [])
    if not urls:
        # Also check for single "url" string for convenience
        url = server_json.get("url")
        if url:
            urls = [url] if isinstance(url, str) else url
        else:
            raise ConfigurationError(
                f"Minecraft server '{name}' must have 'urls' (list) or 'url' (string)"
            )

    desc = server_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return MinecraftServerConfig(name=name, urls=urls, description=description)


def _build_minecraft_config(json_config: dict[str, Any]) -> MinecraftConfig:
    """
    Build Minecraft configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated MinecraftConfig object.

    Raises:
        ConfigurationError: If Minecraft is enabled but required values
            (announcement_channel_id, servers) are not properly configured.

    Environment Variables:
        - MINECRAFT_ENABLED: Whether Minecraft integration is enabled
        - MINECRAFT_ANNOUNCEMENT_CHANNEL_ID: Channel for player join announcements
        - MINECRAFT_ALERT_CHANNEL_ID: Channel for server status alerts

    Note: Server configuration must be done via JSON config file as it requires
    complex nested structures. Environment variables can override channel IDs
    and schedule settings.
    """
    minecraft_json = json_config.get("minecraft", {})

    # Check if enabled (defaults to False since it's a new feature)
    enabled_env = _get_env_bool("MINECRAFT_ENABLED")
    enabled = (
        enabled_env if enabled_env is not None else minecraft_json.get("enabled", False)
    )

    # Channel IDs
    announcement_channel_id = _get_env_int(
        "MINECRAFT_ANNOUNCEMENT_CHANNEL_ID"
    ) or minecraft_json.get("announcement_channel_id")

    alert_channel_id = _get_env_int("MINECRAFT_ALERT_CHANNEL_ID") or minecraft_json.get(
        "alert_channel_id"
    )

    # Validate channels if enabled
    if enabled and not announcement_channel_id:
        raise ConfigurationError(
            "Minecraft announcement channel ID is required when enabled. "
            "Set MINECRAFT_ANNOUNCEMENT_CHANNEL_ID environment variable or "
            "'minecraft.announcement_channel_id' in config.json"
        )

    # Build server configs from JSON (no env var support for server list)
    servers_json = minecraft_json.get("servers", [])
    servers: list[MinecraftServerConfig] = []

    for server_json in servers_json:
        servers.append(_build_minecraft_server_config(server_json))

    if enabled and not servers:
        raise ConfigurationError(
            "At least one Minecraft server must be configured when enabled. "
            "Add servers to 'minecraft.servers' in config.json"
        )

    # Build nested schedule config
    schedule_json = minecraft_json.get("schedule", {})
    schedule_config = _build_minecraft_schedule_config(schedule_json)

    return MinecraftConfig(
        enabled=enabled,
        announcement_channel_id=announcement_channel_id,
        alert_channel_id=alert_channel_id,
        servers=servers,
        schedule=schedule_config,
    )


def _build_nextcloud_config(json_config: dict[str, Any]) -> NextCloudConfig:
    """
    Build NextCloud configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated NextCloudConfig object.

    Raises:
        ConfigurationError: If NextCloud is enabled but required credentials
            are not properly configured.

    Environment Variables:
        - NEXTCLOUD_ENABLED: Whether NextCloud integration is enabled
        - NEXTCLOUD_URL: NextCloud server URL(s), comma-separated for failover
        - NEXTCLOUD_ADMIN_USER: Admin username for OCS API
        - NEXTCLOUD_ADMIN_PASSWORD: Admin password for OCS API
    """
    nextcloud_json = json_config.get("nextcloud", {})

    # Check if enabled (defaults to False)
    enabled_env = _get_env_bool("NEXTCLOUD_ENABLED")
    enabled = (
        enabled_env if enabled_env is not None else nextcloud_json.get("enabled", False)
    )

    # URLs: env var takes precedence, supports comma-separated list
    urls_from_env = _get_env_list("NEXTCLOUD_URL")
    if urls_from_env:
        urls = urls_from_env
    else:
        urls_from_json = nextcloud_json.get("urls")
        if urls_from_json is not None:
            if isinstance(urls_from_json, list):
                urls = urls_from_json
            else:
                urls = [urls_from_json]
        else:
            url_from_json = nextcloud_json.get("url")
            if url_from_json:
                urls = [url_from_json] if isinstance(url_from_json, str) else url_from_json
            else:
                urls = []

    if enabled and not urls:
        raise ConfigurationError(
            "NextCloud URL is required when enabled. Set NEXTCLOUD_URL environment "
            "variable or 'nextcloud.url'/'nextcloud.urls' in config.json"
        )

    # Admin credentials
    admin_user = _get_env("NEXTCLOUD_ADMIN_USER") or nextcloud_json.get("admin_user", "")
    admin_password = (
        _get_env("NEXTCLOUD_ADMIN_PASSWORD") or nextcloud_json.get("admin_password", "")
    )

    if enabled and (not admin_user or not admin_password):
        raise ConfigurationError(
            "NextCloud admin credentials are required when enabled. Set "
            "NEXTCLOUD_ADMIN_USER and NEXTCLOUD_ADMIN_PASSWORD environment variables "
            "or 'nextcloud.admin_user' and 'nextcloud.admin_password' in config.json"
        )

    desc = nextcloud_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return NextCloudConfig(
        enabled=enabled,
        urls=urls,
        admin_user=admin_user,
        admin_password=admin_password,
        description=description,
    )


def _build_navidrome_config(json_config: dict[str, Any]) -> NavidromeConfig:
    """
    Build Navidrome configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated NavidromeConfig object.

    Raises:
        ConfigurationError: If Navidrome is enabled but required credentials
            are not properly configured.

    Environment Variables:
        - NAVIDROME_ENABLED: Whether Navidrome integration is enabled
        - NAVIDROME_URL: Navidrome server URL(s), comma-separated for failover
        - NAVIDROME_ADMIN_USER: Admin username for API
        - NAVIDROME_ADMIN_PASSWORD: Admin password for API
    """
    navidrome_json = json_config.get("navidrome", {})

    # Check if enabled (defaults to False)
    enabled_env = _get_env_bool("NAVIDROME_ENABLED")
    enabled = (
        enabled_env if enabled_env is not None else navidrome_json.get("enabled", False)
    )

    # URLs: env var takes precedence, supports comma-separated list
    urls_from_env = _get_env_list("NAVIDROME_URL")
    if urls_from_env:
        urls = urls_from_env
    else:
        urls_from_json = navidrome_json.get("urls")
        if urls_from_json is not None:
            if isinstance(urls_from_json, list):
                urls = urls_from_json
            else:
                urls = [urls_from_json]
        else:
            url_from_json = navidrome_json.get("url")
            if url_from_json:
                urls = [url_from_json] if isinstance(url_from_json, str) else url_from_json
            else:
                urls = []

    if enabled and not urls:
        raise ConfigurationError(
            "Navidrome URL is required when enabled. Set NAVIDROME_URL environment "
            "variable or 'navidrome.url'/'navidrome.urls' in config.json"
        )

    # Admin credentials
    admin_user = _get_env("NAVIDROME_ADMIN_USER") or navidrome_json.get("admin_user", "")
    admin_password = (
        _get_env("NAVIDROME_ADMIN_PASSWORD") or navidrome_json.get("admin_password", "")
    )

    if enabled and (not admin_user or not admin_password):
        raise ConfigurationError(
            "Navidrome admin credentials are required when enabled. Set "
            "NAVIDROME_ADMIN_USER and NAVIDROME_ADMIN_PASSWORD environment variables "
            "or 'navidrome.admin_user' and 'navidrome.admin_password' in config.json"
        )

    desc = navidrome_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return NavidromeConfig(
        enabled=enabled,
        urls=urls,
        admin_user=admin_user,
        admin_password=admin_password,
        description=description,
    )


def _build_organizr_config(json_config: dict[str, Any]) -> OrganizrConfig:
    """
    Build Organizr configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated OrganizrConfig object.

    Raises:
        ConfigurationError: If Organizr is enabled but required credentials
            are not properly configured.

    Environment Variables:
        - ORGANIZR_ENABLED: Whether Organizr integration is enabled
        - ORGANIZR_URL: Organizr server URL(s), comma-separated for failover
        - ORGANIZR_ADMIN_USER: Admin username for API
        - ORGANIZR_ADMIN_PASSWORD: Admin password for API
    """
    organizr_json = json_config.get("organizr", {})

    enabled_env = _get_env_bool("ORGANIZR_ENABLED")
    enabled = (
        enabled_env
        if enabled_env is not None
        else organizr_json.get("enabled", False)
    )

    urls_from_env = _get_env_list("ORGANIZR_URL")
    if urls_from_env:
        urls = urls_from_env
    else:
        urls_from_json = organizr_json.get("urls")
        if urls_from_json is not None:
            if isinstance(urls_from_json, list):
                urls = urls_from_json
            else:
                urls = [urls_from_json]
        else:
            url_from_json = organizr_json.get("url")
            if url_from_json:
                urls = (
                    [url_from_json]
                    if isinstance(url_from_json, str)
                    else url_from_json
                )
            else:
                urls = []

    if enabled and not urls:
        raise ConfigurationError(
            "Organizr URL is required when enabled. Set ORGANIZR_URL environment "
            "variable or 'organizr.url'/'organizr.urls' in config.json"
        )

    admin_user = _get_env("ORGANIZR_ADMIN_USER") or organizr_json.get(
        "admin_user", ""
    )
    admin_password = _get_env("ORGANIZR_ADMIN_PASSWORD") or organizr_json.get(
        "admin_password", ""
    )

    if enabled and (not admin_user or not admin_password):
        raise ConfigurationError(
            "Organizr admin credentials are required when enabled. Set "
            "ORGANIZR_ADMIN_USER and ORGANIZR_ADMIN_PASSWORD environment variables "
            "or 'organizr.admin_user' and 'organizr.admin_password' in config.json"
        )

    desc = organizr_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return OrganizrConfig(
        enabled=enabled,
        urls=urls,
        admin_user=admin_user,
        admin_password=admin_password,
        description=description,
    )


def _build_romm_config(json_config: dict[str, Any]) -> RommConfig:
    """
    Build Romm configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated RommConfig object.

    Raises:
        ConfigurationError: If Romm is enabled but required credentials
            are not properly configured.

    Environment Variables:
        - ROMM_ENABLED: Whether Romm integration is enabled
        - ROMM_URL: Romm server URL(s), comma-separated for failover
        - ROMM_ADMIN_USER: Admin username for API
        - ROMM_ADMIN_PASSWORD: Admin password for API
    """
    romm_json = json_config.get("romm", {})

    # Check if enabled (defaults to False)
    enabled_env = _get_env_bool("ROMM_ENABLED")
    enabled = enabled_env if enabled_env is not None else romm_json.get("enabled", False)

    # URLs: env var takes precedence, supports comma-separated list
    urls_from_env = _get_env_list("ROMM_URL")
    if urls_from_env:
        urls = urls_from_env
    else:
        urls_from_json = romm_json.get("urls")
        if urls_from_json is not None:
            if isinstance(urls_from_json, list):
                urls = urls_from_json
            else:
                urls = [urls_from_json]
        else:
            url_from_json = romm_json.get("url")
            if url_from_json:
                urls = [url_from_json] if isinstance(url_from_json, str) else url_from_json
            else:
                urls = []

    if enabled and not urls:
        raise ConfigurationError(
            "Romm URL is required when enabled. Set ROMM_URL environment "
            "variable or 'romm.url'/'romm.urls' in config.json"
        )

    # Admin credentials
    admin_user = _get_env("ROMM_ADMIN_USER") or romm_json.get("admin_user", "")
    admin_password = _get_env("ROMM_ADMIN_PASSWORD") or romm_json.get("admin_password", "")

    if enabled and (not admin_user or not admin_password):
        raise ConfigurationError(
            "Romm admin credentials are required when enabled. Set "
            "ROMM_ADMIN_USER and ROMM_ADMIN_PASSWORD environment variables "
            "or 'romm.admin_user' and 'romm.admin_password' in config.json"
        )

    desc = romm_json.get("description")
    description = desc.strip() if isinstance(desc, str) and desc else ""

    return RommConfig(
        enabled=enabled,
        urls=urls,
        admin_user=admin_user,
        admin_password=admin_password,
        description=description,
    )


def _build_registration_config(json_config: dict[str, Any]) -> RegistrationConfig:
    """
    Build registration feature configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        Populated RegistrationConfig object.

    Environment Variables:
        - REGISTRATION_ENABLED: Whether registration feature is enabled
        - REGISTRATION_REGISTRY_FILE: Path to user registry JSON file
    """
    registration_json = json_config.get("registration", {})

    # Check if enabled (defaults to False)
    enabled_env = _get_env_bool("REGISTRATION_ENABLED")
    enabled = (
        enabled_env
        if enabled_env is not None
        else registration_json.get("enabled", False)
    )

    # Registry file path
    registry_file = (
        os.getenv("REGISTRATION_REGISTRY_FILE")
        or registration_json.get("registry_file", "data/user_registry.json")
    )

    return RegistrationConfig(enabled=enabled, registry_file=registry_file)


def _build_additional_links_config(json_config: dict[str, Any]) -> list[AdditionalLinkConfig]:
    """
    Build the list of additional name/URL links from JSON.

    Used in the /help command to show extra links (e.g. Wiki, Status Page).
    Entries missing "name" or "url" are skipped.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        List of AdditionalLinkConfig. Empty if key is missing or invalid.
    """
    raw = json_config.get("additional_links")
    if not isinstance(raw, list):
        return []
    result: list[AdditionalLinkConfig] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        if name is not None and url is not None and isinstance(name, str) and isinstance(url, str) and name.strip() and url.strip():
            desc = item.get("description")
            description = desc.strip() if isinstance(desc, str) and desc else ""
            result.append(
                AdditionalLinkConfig(
                    name=name.strip(),
                    url=url.strip(),
                    description=description,
                )
            )
    return result


def _build_logging_config(json_config: dict[str, Any]) -> LoggingConfig:
    """
    Build logging configuration from JSON and environment variables.

    Environment variables take precedence over JSON values.

    Args:
        json_config: Parsed JSON configuration dictionary.

    Returns:
        LoggingConfig with log directory, level, and output settings.
    """
    logging_json = json_config.get("logging", {})
    if not isinstance(logging_json, dict):
        logging_json = {}

    # Environment variable overrides
    log_directory = (
        os.environ.get("LOG_DIRECTORY")
        or logging_json.get("log_directory")
        or "logs"
    )

    log_level = (
        os.environ.get("LOG_LEVEL")
        or logging_json.get("log_level")
        or "INFO"
    )

    # Boolean environment variables
    log_to_console_env = os.environ.get("LOG_TO_CONSOLE")
    if log_to_console_env is not None:
        log_to_console = log_to_console_env.lower() in ("true", "1", "yes")
    else:
        log_to_console = logging_json.get("log_to_console", True)

    log_to_file_env = os.environ.get("LOG_TO_FILE")
    if log_to_file_env is not None:
        log_to_file = log_to_file_env.lower() in ("true", "1", "yes")
    else:
        log_to_file = logging_json.get("log_to_file", True)

    return LoggingConfig(
        log_directory=log_directory,
        log_level=log_level.upper(),
        log_to_console=log_to_console,
        log_to_file=log_to_file,
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
        >>> print(config.jellyfin.schedule.announcement_times)
        >>> print(config.jellyfin.content_types)
        >>> print(config.minecraft.servers[0].name)
        >>> print(config.registration.enabled)
    """
    if config_path is None:
        config_path = Path("config.json")

    # Load JSON config (returns empty dict if file doesn't exist)
    json_config = _load_json_config(config_path)

    # Build each configuration section
    discord_config = _build_discord_config(json_config)
    jellyfin_config = _build_jellyfin_config(json_config)
    minecraft_config = _build_minecraft_config(json_config)
    nextcloud_config = _build_nextcloud_config(json_config)
    navidrome_config = _build_navidrome_config(json_config)
    organizr_config = _build_organizr_config(json_config)
    romm_config = _build_romm_config(json_config)
    registration_config = _build_registration_config(json_config)
    additional_links = _build_additional_links_config(json_config)
    logging_config = _build_logging_config(json_config)

    return Config(
        discord=discord_config,
        jellyfin=jellyfin_config,
        minecraft=minecraft_config,
        nextcloud=nextcloud_config,
        navidrome=navidrome_config,
        organizr=organizr_config,
        romm=romm_config,
        registration=registration_config,
        additional_links=additional_links,
        logging=logging_config,
    )

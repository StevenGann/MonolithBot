"""
Configuration loader for MonolithBot.

Supports loading configuration from:
1. JSON file (config.json) for local development
2. Environment variables for Docker deployment

Environment variables take precedence over JSON file values.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DiscordConfig:
    """Discord-related configuration."""

    token: str
    announcement_channel_id: int
    alert_channel_id: Optional[int] = None

    def __post_init__(self):
        if self.alert_channel_id is None:
            self.alert_channel_id = self.announcement_channel_id


@dataclass
class JellyfinConfig:
    """Jellyfin server configuration."""

    url: str
    api_key: str

    def __post_init__(self):
        self.url = self.url.rstrip("/")


@dataclass
class ScheduleConfig:
    """Scheduling configuration."""

    announcement_times: list[str] = field(default_factory=lambda: ["17:00"])
    timezone: str = "America/Los_Angeles"
    health_check_interval_minutes: int = 5
    lookback_hours: int = 24


@dataclass
class Config:
    """Main configuration container."""

    discord: DiscordConfig
    jellyfin: JellyfinConfig
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    content_types: list[str] = field(default_factory=lambda: ["Movie", "Series", "Audio"])


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required values."""

    pass


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable value."""
    return os.environ.get(key, default)


def _get_env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    """Get environment variable as integer."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(f"Environment variable {key} must be an integer, got: {value}")


def _get_env_list(key: str, default: Optional[list[str]] = None) -> Optional[list[str]]:
    """Get environment variable as comma-separated list."""
    value = os.environ.get(key)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_json_config(config_path: Path) -> dict:
    """Load configuration from JSON file."""
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in config file: {e}")


def _build_discord_config(json_config: dict) -> DiscordConfig:
    """Build Discord configuration from JSON and environment variables."""
    discord_json = json_config.get("discord", {})

    token = _get_env("DISCORD_TOKEN") or discord_json.get("token")
    if not token:
        raise ConfigurationError(
            "Discord token is required. Set DISCORD_TOKEN environment variable "
            "or 'discord.token' in config.json"
        )

    announcement_channel_id = _get_env_int("DISCORD_ANNOUNCEMENT_CHANNEL_ID") or discord_json.get(
        "announcement_channel_id"
    )
    if not announcement_channel_id:
        raise ConfigurationError(
            "Discord announcement channel ID is required. Set DISCORD_ANNOUNCEMENT_CHANNEL_ID "
            "environment variable or 'discord.announcement_channel_id' in config.json"
        )

    alert_channel_id = _get_env_int("DISCORD_ALERT_CHANNEL_ID") or discord_json.get(
        "alert_channel_id"
    )

    return DiscordConfig(
        token=token,
        announcement_channel_id=announcement_channel_id,
        alert_channel_id=alert_channel_id,
    )


def _build_jellyfin_config(json_config: dict) -> JellyfinConfig:
    """Build Jellyfin configuration from JSON and environment variables."""
    jellyfin_json = json_config.get("jellyfin", {})

    url = _get_env("JELLYFIN_URL") or jellyfin_json.get("url")
    if not url:
        raise ConfigurationError(
            "Jellyfin URL is required. Set JELLYFIN_URL environment variable "
            "or 'jellyfin.url' in config.json"
        )

    api_key = _get_env("JELLYFIN_API_KEY") or jellyfin_json.get("api_key")
    if not api_key:
        raise ConfigurationError(
            "Jellyfin API key is required. Set JELLYFIN_API_KEY environment variable "
            "or 'jellyfin.api_key' in config.json"
        )

    return JellyfinConfig(url=url, api_key=api_key)


def _build_schedule_config(json_config: dict) -> ScheduleConfig:
    """Build schedule configuration from JSON and environment variables."""
    schedule_json = json_config.get("schedule", {})

    announcement_times = _get_env_list("SCHEDULE_ANNOUNCEMENT_TIMES") or schedule_json.get(
        "announcement_times", ["17:00"]
    )

    timezone = _get_env("SCHEDULE_TIMEZONE") or schedule_json.get(
        "timezone", "America/Los_Angeles"
    )

    health_check_interval = _get_env_int("SCHEDULE_HEALTH_CHECK_INTERVAL") or schedule_json.get(
        "health_check_interval_minutes", 5
    )

    lookback_hours = _get_env_int("SCHEDULE_LOOKBACK_HOURS") or schedule_json.get(
        "lookback_hours", 24
    )

    return ScheduleConfig(
        announcement_times=announcement_times,
        timezone=timezone,
        health_check_interval_minutes=health_check_interval,
        lookback_hours=lookback_hours,
    )


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from JSON file and environment variables.

    Environment variables take precedence over JSON file values.

    Args:
        config_path: Path to JSON config file. Defaults to 'config.json' in current directory.

    Returns:
        Config object with all settings.

    Raises:
        ConfigurationError: If required configuration is missing or invalid.
    """
    if config_path is None:
        config_path = Path("config.json")

    json_config = _load_json_config(config_path)

    discord_config = _build_discord_config(json_config)
    jellyfin_config = _build_jellyfin_config(json_config)
    schedule_config = _build_schedule_config(json_config)

    content_types = _get_env_list("CONTENT_TYPES") or json_config.get(
        "content_types", ["Movie", "Series", "Audio"]
    )

    return Config(
        discord=discord_config,
        jellyfin=jellyfin_config,
        schedule=schedule_config,
        content_types=content_types,
    )

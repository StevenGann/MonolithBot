"""
Pytest configuration and shared fixtures for MonolithBot tests.

This module provides reusable fixtures for testing the bot's components,
including mock configurations, Discord objects, and Jellyfin responses.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from bot.config import Config, DiscordConfig, JellyfinConfig, JellyfinScheduleConfig
from bot.services.jellyfin import JellyfinItem, ServerInfo


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def discord_config() -> DiscordConfig:
    """Create a mock Discord configuration."""
    return DiscordConfig(
        token="test-token-12345",
        announcement_channel_id=123456789,
        alert_channel_id=987654321,
    )


@pytest.fixture
def jellyfin_schedule_config() -> JellyfinScheduleConfig:
    """Create a mock Jellyfin schedule configuration."""
    return JellyfinScheduleConfig(
        announcement_times=["09:00", "17:00"],
        suggestion_times=["12:00", "20:00"],
        timezone="America/Los_Angeles",
        health_check_interval_minutes=5,
        lookback_hours=24,
        max_items_per_type=10,
    )


@pytest.fixture
def jellyfin_config(jellyfin_schedule_config: JellyfinScheduleConfig) -> JellyfinConfig:
    """Create a mock Jellyfin configuration."""
    return JellyfinConfig(
        enabled=True,
        url="http://localhost:8096",
        api_key="test-api-key-12345",
        content_types=["Movie", "Series", "Audio"],
        schedule=jellyfin_schedule_config,
    )


@pytest.fixture
def config(
    discord_config: DiscordConfig,
    jellyfin_config: JellyfinConfig,
) -> Config:
    """Create a complete mock configuration."""
    return Config(
        discord=discord_config,
        jellyfin=jellyfin_config,
    )


@pytest.fixture
def config_json() -> dict[str, Any]:
    """Create a sample configuration as a JSON-compatible dict."""
    return {
        "discord": {
            "token": "test-token-from-json",
            "announcement_channel_id": 111222333,
            "alert_channel_id": 444555666,
        },
        "jellyfin": {
            "enabled": True,
            "url": "http://jellyfin.local:8096",
            "api_key": "json-api-key",
            "content_types": ["Movie", "Series"],
            "schedule": {
                "announcement_times": ["12:00", "20:00"],
                "suggestion_times": ["10:00", "18:00"],
                "timezone": "UTC",
                "health_check_interval_minutes": 10,
                "lookback_hours": 48,
                "max_items_per_type": 5,
            },
        },
    }


@pytest.fixture
def temp_config_file(tmp_path: Path, config_json: dict[str, Any]) -> Path:
    """Create a temporary config.json file."""
    import json

    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
        json.dump(config_json, f)
    return config_path


# =============================================================================
# Jellyfin Fixtures
# =============================================================================


@pytest.fixture
def server_info() -> ServerInfo:
    """Create a mock Jellyfin server info response."""
    return ServerInfo(
        server_name="Test Monolith",
        version="10.8.13",
        operating_system="Linux",
    )


@pytest.fixture
def jellyfin_movie() -> JellyfinItem:
    """Create a mock Jellyfin movie item."""
    return JellyfinItem(
        id="movie-123",
        name="The Matrix",
        item_type="Movie",
        overview="A computer hacker learns about the true nature of reality.",
        year=1999,
        date_created=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def jellyfin_episode() -> JellyfinItem:
    """Create a mock Jellyfin episode item."""
    return JellyfinItem(
        id="episode-456",
        name="Pilot",
        item_type="Episode",
        overview="The first episode of the series.",
        series_name="Breaking Bad",
        date_created=datetime(2024, 1, 16, 14, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def jellyfin_audio() -> JellyfinItem:
    """Create a mock Jellyfin audio/music item."""
    return JellyfinItem(
        id="audio-789",
        name="Bohemian Rhapsody",
        item_type="Audio",
        artists=["Queen"],
        album="A Night at the Opera",
        date_created=datetime(2024, 1, 17, 8, 15, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def jellyfin_items(
    jellyfin_movie: JellyfinItem,
    jellyfin_episode: JellyfinItem,
    jellyfin_audio: JellyfinItem,
) -> list[JellyfinItem]:
    """Create a list of mixed Jellyfin items."""
    return [jellyfin_movie, jellyfin_episode, jellyfin_audio]


@pytest.fixture
def jellyfin_api_movie_response() -> dict[str, Any]:
    """Create a raw Jellyfin API response for a movie."""
    return {
        "Id": "movie-123",
        "Name": "The Matrix",
        "Type": "Movie",
        "Overview": "A computer hacker learns about the true nature of reality.",
        "ProductionYear": 1999,
        "DateCreated": "2024-01-15T10:30:00.0000000Z",
    }


@pytest.fixture
def jellyfin_api_items_response(
    jellyfin_api_movie_response: dict[str, Any],
) -> dict[str, Any]:
    """Create a raw Jellyfin API /Items response."""
    return {
        "Items": [jellyfin_api_movie_response],
        "TotalRecordCount": 1,
    }


# =============================================================================
# Discord Fixtures
# =============================================================================


@pytest.fixture
def mock_discord_channel() -> MagicMock:
    """Create a mock Discord text channel."""
    channel = MagicMock()
    channel.name = "announcements"
    channel.id = 123456789
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_discord_interaction() -> MagicMock:
    """Create a mock Discord interaction (for slash commands)."""
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def mock_bot(config: Config, mock_discord_channel: MagicMock) -> MagicMock:
    """Create a mock MonolithBot instance."""
    bot = MagicMock()
    bot.config = config
    bot.test_mode = False
    bot.latency = 0.05  # 50ms
    bot.user = MagicMock()
    bot.user.id = 999888777
    bot.user.__str__ = lambda self: "MonolithBot#1234"
    bot.guilds = []
    bot.get_channel = MagicMock(return_value=mock_discord_channel)
    bot.get_cog = MagicMock(return_value=None)
    return bot


# =============================================================================
# Helper Functions
# =============================================================================


def create_jellyfin_item(
    id: str = "test-id",
    name: str = "Test Item",
    item_type: str = "Movie",
    **kwargs: Any,
) -> JellyfinItem:
    """Helper function to create JellyfinItem with custom attributes."""
    return JellyfinItem(
        id=id,
        name=name,
        item_type=item_type,
        **kwargs,
    )

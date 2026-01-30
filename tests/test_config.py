"""
Unit tests for bot/config.py - Configuration loading and validation.

Tests cover:
    - Loading configuration from JSON files
    - Environment variable overrides
    - Required field validation
    - Default values
    - Error handling for invalid configuration
"""

import json
import os
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from bot.config import (
    ConfigurationError,
    DiscordConfig,
    JellyfinConfig,
    JellyfinScheduleConfig,
    MinecraftConfig,
    MinecraftScheduleConfig,
    MinecraftServerConfig,
    load_config,
    _get_env,
    _get_env_bool,
    _get_env_int,
    _get_env_list,
    _load_json_config,
    _build_discord_config,
    _build_jellyfin_config,
    _build_jellyfin_schedule_config,
    _build_minecraft_config,
    _build_minecraft_schedule_config,
    _build_minecraft_server_config,
)


# =============================================================================
# DiscordConfig Tests
# =============================================================================


class TestDiscordConfig:
    """Tests for DiscordConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating DiscordConfig with required fields."""
        config = DiscordConfig(
            token="test-token",
            announcement_channel_id=123456789,
        )
        assert config.token == "test-token"
        assert config.announcement_channel_id == 123456789
        # alert_channel_id should default to announcement_channel_id
        assert config.alert_channel_id == 123456789

    def test_separate_alert_channel(self) -> None:
        """Test providing a separate alert channel ID."""
        config = DiscordConfig(
            token="test-token",
            announcement_channel_id=123456789,
            alert_channel_id=987654321,
        )
        assert config.alert_channel_id == 987654321


class TestJellyfinScheduleConfig:
    """Tests for JellyfinScheduleConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values for schedule config."""
        config = JellyfinScheduleConfig()
        assert config.announcement_times == ["17:00"]
        assert config.suggestion_times == []
        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 5
        assert config.lookback_hours == 24
        assert config.max_items_per_type == 10

    def test_custom_values(self) -> None:
        """Test custom values for schedule config."""
        config = JellyfinScheduleConfig(
            announcement_times=["09:00", "21:00"],
            suggestion_times=["12:00", "18:00"],
            timezone="UTC",
            health_check_interval_minutes=10,
            lookback_hours=48,
            max_items_per_type=5,
        )
        assert config.announcement_times == ["09:00", "21:00"]
        assert config.suggestion_times == ["12:00", "18:00"]
        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 10
        assert config.lookback_hours == 48
        assert config.max_items_per_type == 5


class TestJellyfinConfig:
    """Tests for JellyfinConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating JellyfinConfig with required fields."""
        config = JellyfinConfig(
            enabled=True,
            urls=["http://localhost:8096"],
            api_key="test-api-key",
        )
        assert config.enabled is True
        assert config.urls == ["http://localhost:8096"]
        assert config.url == "http://localhost:8096"  # Backward compat property
        assert config.api_key == "test-api-key"
        assert config.content_types == ["Movie", "Series", "Audio"]

    def test_trailing_slash_removed(self) -> None:
        """Test that trailing slashes are removed from URLs."""
        config = JellyfinConfig(
            enabled=True,
            urls=["http://localhost:8096/"],
            api_key="test-api-key",
        )
        assert config.urls == ["http://localhost:8096"]
        assert config.url == "http://localhost:8096"

    def test_multiple_trailing_slashes_removed(self) -> None:
        """Test that multiple trailing slashes are removed."""
        config = JellyfinConfig(
            enabled=True,
            urls=["http://localhost:8096///"],
            api_key="test-api-key",
        )
        assert config.urls == ["http://localhost:8096"]
        assert config.url == "http://localhost:8096"

    def test_multiple_urls(self) -> None:
        """Test creating JellyfinConfig with multiple URLs for failover."""
        config = JellyfinConfig(
            enabled=True,
            urls=[
                "http://primary.local:8096/",
                "http://secondary.local:8096/",
                "http://192.168.1.100:8096/",
            ],
            api_key="test-api-key",
        )
        assert len(config.urls) == 3
        assert config.urls[0] == "http://primary.local:8096"
        assert config.urls[1] == "http://secondary.local:8096"
        assert config.urls[2] == "http://192.168.1.100:8096"
        # .url property returns the first (primary) URL
        assert config.url == "http://primary.local:8096"

    def test_empty_urls_url_property(self) -> None:
        """Test that url property returns empty string when no URLs."""
        config = JellyfinConfig(
            enabled=False,
            urls=[],
            api_key="",
        )
        assert config.url == ""

    def test_default_schedule(self) -> None:
        """Test that default schedule is created."""
        config = JellyfinConfig(
            enabled=True,
            urls=["http://localhost:8096"],
            api_key="test-api-key",
        )
        assert config.schedule.announcement_times == ["17:00"]
        assert config.schedule.timezone == "America/Los_Angeles"

    def test_disabled_config(self) -> None:
        """Test creating disabled JellyfinConfig."""
        config = JellyfinConfig(
            enabled=False,
            urls=[],
            api_key="",
        )
        assert config.enabled is False


# =============================================================================
# Environment Variable Helper Tests
# =============================================================================


class TestEnvHelpers:
    """Tests for environment variable helper functions."""

    def test_get_env_returns_value(self) -> None:
        """Test _get_env returns environment variable value."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            assert _get_env("TEST_VAR") == "test_value"

    def test_get_env_returns_default(self) -> None:
        """Test _get_env returns default when var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _get_env("NONEXISTENT_VAR") is None
            assert _get_env("NONEXISTENT_VAR", "default") == "default"

    def test_get_env_bool_returns_true(self) -> None:
        """Test _get_env_bool parses true values."""
        for val in ["true", "True", "TRUE", "1", "yes", "YES"]:
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _get_env_bool("TEST_BOOL") is True

    def test_get_env_bool_returns_false(self) -> None:
        """Test _get_env_bool parses false values."""
        for val in ["false", "False", "FALSE", "0", "no", "NO", "anything"]:
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _get_env_bool("TEST_BOOL") is False

    def test_get_env_bool_returns_default(self) -> None:
        """Test _get_env_bool returns default when var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _get_env_bool("NONEXISTENT_VAR") is None
            assert _get_env_bool("NONEXISTENT_VAR", True) is True
            assert _get_env_bool("NONEXISTENT_VAR", False) is False

    def test_get_env_int_returns_int(self) -> None:
        """Test _get_env_int parses integer values."""
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert _get_env_int("TEST_INT") == 42

    def test_get_env_int_returns_default(self) -> None:
        """Test _get_env_int returns default when var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _get_env_int("NONEXISTENT_VAR") is None
            assert _get_env_int("NONEXISTENT_VAR", 99) == 99

    def test_get_env_int_raises_on_invalid(self) -> None:
        """Test _get_env_int raises ConfigurationError on invalid value."""
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            with pytest.raises(ConfigurationError) as exc_info:
                _get_env_int("TEST_INT")
            assert "must be an integer" in str(exc_info.value)

    def test_get_env_list_parses_comma_separated(self) -> None:
        """Test _get_env_list parses comma-separated values."""
        with patch.dict(os.environ, {"TEST_LIST": "a,b,c"}):
            assert _get_env_list("TEST_LIST") == ["a", "b", "c"]

    def test_get_env_list_strips_whitespace(self) -> None:
        """Test _get_env_list strips whitespace from items."""
        with patch.dict(os.environ, {"TEST_LIST": " a , b , c "}):
            assert _get_env_list("TEST_LIST") == ["a", "b", "c"]

    def test_get_env_list_ignores_empty_items(self) -> None:
        """Test _get_env_list ignores empty items."""
        with patch.dict(os.environ, {"TEST_LIST": "a,,b, ,c"}):
            assert _get_env_list("TEST_LIST") == ["a", "b", "c"]

    def test_get_env_list_returns_default(self) -> None:
        """Test _get_env_list returns default when var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _get_env_list("NONEXISTENT_VAR") is None
            assert _get_env_list("NONEXISTENT_VAR", ["x"]) == ["x"]


# =============================================================================
# JSON Config Loading Tests
# =============================================================================


class TestLoadJsonConfig:
    """Tests for _load_json_config function."""

    def test_load_valid_json(self, tmp_path: Path) -> None:
        """Test loading a valid JSON config file."""
        config_path = tmp_path / "config.json"
        config_data = {"discord": {"token": "test"}}
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        result = _load_json_config(config_path)
        assert result == config_data

    def test_returns_empty_dict_if_file_not_exists(self, tmp_path: Path) -> None:
        """Test returning empty dict when file doesn't exist."""
        config_path = tmp_path / "nonexistent.json"
        result = _load_json_config(config_path)
        assert result == {}

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        """Test raising ConfigurationError on invalid JSON."""
        config_path = tmp_path / "invalid.json"
        with open(config_path, "w") as f:
            f.write("{ invalid json }")

        with pytest.raises(ConfigurationError) as exc_info:
            _load_json_config(config_path)
        assert "Invalid JSON" in str(exc_info.value)


# =============================================================================
# Build Config Section Tests
# =============================================================================


class TestBuildDiscordConfig:
    """Tests for _build_discord_config function."""

    def test_loads_from_json(self) -> None:
        """Test loading Discord config from JSON."""
        json_config = {
            "discord": {
                "token": "json-token",
                "announcement_channel_id": 123,
                "alert_channel_id": 456,
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_discord_config(json_config)
        assert config.token == "json-token"
        assert config.announcement_channel_id == 123
        assert config.alert_channel_id == 456

    def test_env_overrides_json(self) -> None:
        """Test environment variables override JSON values."""
        json_config = {
            "discord": {
                "token": "json-token",
                "announcement_channel_id": 123,
            }
        }
        env_vars = {
            "DISCORD_TOKEN": "env-token",
            "DISCORD_ANNOUNCEMENT_CHANNEL_ID": "789",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_discord_config(json_config)
        assert config.token == "env-token"
        assert config.announcement_channel_id == 789

    def test_raises_on_missing_token(self) -> None:
        """Test raising error when token is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_discord_config({})
            assert "Discord token is required" in str(exc_info.value)

    def test_raises_on_missing_channel_id(self) -> None:
        """Test raising error when announcement channel ID is missing."""
        json_config = {"discord": {"token": "test-token"}}
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_discord_config(json_config)
            assert "announcement channel ID is required" in str(exc_info.value)


class TestBuildJellyfinScheduleConfig:
    """Tests for _build_jellyfin_schedule_config function."""

    def test_uses_defaults(self) -> None:
        """Test using default values when nothing is configured."""
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_schedule_config({})
        assert config.announcement_times == ["17:00"]
        assert config.suggestion_times == []
        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 5
        assert config.lookback_hours == 24

    def test_loads_from_json(self) -> None:
        """Test loading schedule config from JSON."""
        schedule_json = {
            "announcement_times": ["09:00", "21:00"],
            "suggestion_times": ["12:00", "18:00"],
            "timezone": "UTC",
            "health_check_interval_minutes": 10,
            "lookback_hours": 48,
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_schedule_config(schedule_json)
        assert config.announcement_times == ["09:00", "21:00"]
        assert config.suggestion_times == ["12:00", "18:00"]
        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 10
        assert config.lookback_hours == 48

    def test_env_overrides_json(self) -> None:
        """Test environment variables override JSON values."""
        schedule_json = {
            "announcement_times": ["12:00"],
            "timezone": "UTC",
        }
        env_vars = {
            "JELLYFIN_SCHEDULE_ANNOUNCEMENT_TIMES": "06:00,18:00",
            "JELLYFIN_SCHEDULE_TIMEZONE": "Europe/London",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_jellyfin_schedule_config(schedule_json)
        assert config.announcement_times == ["06:00", "18:00"]
        assert config.timezone == "Europe/London"


class TestBuildJellyfinConfig:
    """Tests for _build_jellyfin_config function."""

    def test_loads_from_json(self) -> None:
        """Test loading Jellyfin config from JSON."""
        json_config = {
            "jellyfin": {
                "enabled": True,
                "url": "http://test:8096",
                "api_key": "test-key",
                "content_types": ["Movie", "Series"],
                "schedule": {
                    "announcement_times": ["12:00"],
                },
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_config(json_config)
        assert config.enabled is True
        assert config.url == "http://test:8096"
        assert config.api_key == "test-key"
        assert config.content_types == ["Movie", "Series"]
        assert config.schedule.announcement_times == ["12:00"]

    def test_env_overrides_json(self) -> None:
        """Test environment variables override JSON values."""
        json_config = {
            "jellyfin": {
                "enabled": True,
                "url": "http://json:8096",
                "api_key": "json-key",
            }
        }
        env_vars = {
            "JELLYFIN_URL": "http://env:8096",
            "JELLYFIN_API_KEY": "env-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_jellyfin_config(json_config)
        assert config.url == "http://env:8096"
        assert config.api_key == "env-key"

    def test_enabled_defaults_to_true(self) -> None:
        """Test that enabled defaults to True for backward compatibility."""
        json_config = {
            "jellyfin": {
                "url": "http://test:8096",
                "api_key": "test-key",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_config(json_config)
        assert config.enabled is True

    def test_disabled_jellyfin_no_url_required(self) -> None:
        """Test that URL/API key not required when disabled."""
        json_config = {
            "jellyfin": {
                "enabled": False,
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_config(json_config)
        assert config.enabled is False
        assert config.url == ""
        assert config.api_key == ""

    def test_raises_on_missing_url_when_enabled(self) -> None:
        """Test raising error when URL is missing and enabled."""
        json_config = {
            "jellyfin": {
                "enabled": True,
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_jellyfin_config(json_config)
            assert "Jellyfin URL is required" in str(exc_info.value)

    def test_raises_on_missing_api_key_when_enabled(self) -> None:
        """Test raising error when API key is missing and enabled."""
        json_config = {
            "jellyfin": {
                "enabled": True,
                "url": "http://test:8096",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_jellyfin_config(json_config)
            assert "Jellyfin API key is required" in str(exc_info.value)


# =============================================================================
# Full Config Loading Tests
# =============================================================================


class TestLoadConfig:
    """Tests for the main load_config function."""

    def test_loads_complete_config_from_json(
        self, temp_config_file: Path, config_json: dict[str, Any]
    ) -> None:
        """Test loading a complete configuration from JSON file."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config(temp_config_file)

        assert config.discord.token == config_json["discord"]["token"]
        assert (
            config.discord.announcement_channel_id
            == config_json["discord"]["announcement_channel_id"]
        )
        assert config.jellyfin.enabled == config_json["jellyfin"]["enabled"]
        assert config.jellyfin.url == config_json["jellyfin"]["url"]
        assert config.jellyfin.api_key == config_json["jellyfin"]["api_key"]
        assert config.jellyfin.content_types == config_json["jellyfin"]["content_types"]
        assert (
            config.jellyfin.schedule.announcement_times
            == config_json["jellyfin"]["schedule"]["announcement_times"]
        )

    def test_loads_from_env_only(self, tmp_path: Path) -> None:
        """Test loading configuration from environment variables only."""
        env_vars = {
            "DISCORD_TOKEN": "env-only-token",
            "DISCORD_ANNOUNCEMENT_CHANNEL_ID": "111222333",
            "JELLYFIN_URL": "http://env-only:8096",
            "JELLYFIN_API_KEY": "env-only-key",
        }
        # Use a non-existent config file path
        config_path = tmp_path / "nonexistent.json"

        with patch.dict(os.environ, env_vars, clear=True):
            config = load_config(config_path)

        assert config.discord.token == "env-only-token"
        assert config.discord.announcement_channel_id == 111222333
        assert config.jellyfin.url == "http://env-only:8096"
        assert config.jellyfin.api_key == "env-only-key"

    def test_default_config_path(self) -> None:
        """Test that default config path is config.json in cwd."""
        env_vars = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_ANNOUNCEMENT_CHANNEL_ID": "123",
            "JELLYFIN_URL": "http://test:8096",
            "JELLYFIN_API_KEY": "test-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            # This should not raise even if config.json doesn't exist
            # because env vars provide all required values
            config = load_config()
            assert config.discord.token == "test-token"

    def test_jellyfin_disabled_via_env(self, tmp_path: Path) -> None:
        """Test disabling Jellyfin via environment variable."""
        env_vars = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_ANNOUNCEMENT_CHANNEL_ID": "123",
            "JELLYFIN_ENABLED": "false",
        }
        config_path = tmp_path / "nonexistent.json"

        with patch.dict(os.environ, env_vars, clear=True):
            config = load_config(config_path)

        assert config.jellyfin.enabled is False


# =============================================================================
# MinecraftScheduleConfig Tests
# =============================================================================


class TestMinecraftScheduleConfig:
    """Tests for MinecraftScheduleConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values for schedule config."""
        config = MinecraftScheduleConfig()
        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 1
        assert config.player_check_interval_seconds == 30

    def test_custom_values(self) -> None:
        """Test custom values for schedule config."""
        config = MinecraftScheduleConfig(
            timezone="UTC",
            health_check_interval_minutes=5,
            player_check_interval_seconds=15,
        )
        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 5
        assert config.player_check_interval_seconds == 15


# =============================================================================
# MinecraftServerConfig Tests
# =============================================================================


class TestMinecraftServerConfig:
    """Tests for MinecraftServerConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating server config with required fields."""
        config = MinecraftServerConfig(
            name="Survival",
            urls=["localhost:25565"],
        )
        assert config.name == "Survival"
        assert config.urls == ["localhost:25565"]

    def test_multiple_urls(self) -> None:
        """Test server config with multiple URLs for failover."""
        config = MinecraftServerConfig(
            name="Survival",
            urls=["mc.example.com:25565", "192.168.1.100:25565", "backup.local:25565"],
        )
        assert len(config.urls) == 3
        assert config.urls[0] == "mc.example.com:25565"

    def test_empty_name_raises_error(self) -> None:
        """Test that empty server name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MinecraftServerConfig(name="", urls=["localhost:25565"])
        assert "name cannot be empty" in str(exc_info.value)

    def test_empty_urls_raises_error(self) -> None:
        """Test that empty URLs list raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MinecraftServerConfig(name="Survival", urls=[])
        assert "must have at least one URL" in str(exc_info.value)


# =============================================================================
# MinecraftConfig Tests
# =============================================================================


class TestMinecraftConfig:
    """Tests for MinecraftConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating MinecraftConfig with required fields."""
        config = MinecraftConfig(
            enabled=True,
            announcement_channel_id=123456789,
            alert_channel_id=987654321,
            servers=[MinecraftServerConfig(name="Survival", urls=["localhost:25565"])],
        )
        assert config.enabled is True
        assert config.announcement_channel_id == 123456789
        assert config.alert_channel_id == 987654321
        assert len(config.servers) == 1

    def test_alert_channel_defaults_to_announcement(self) -> None:
        """Test that alert_channel_id defaults to announcement_channel_id."""
        config = MinecraftConfig(
            enabled=True,
            announcement_channel_id=123456789,
            servers=[MinecraftServerConfig(name="Survival", urls=["localhost:25565"])],
        )
        assert config.alert_channel_id == 123456789

    def test_disabled_by_default(self) -> None:
        """Test that Minecraft is disabled by default when channels are None."""
        config = MinecraftConfig(enabled=False)
        assert config.enabled is False
        assert config.servers == []

    def test_multiple_servers(self) -> None:
        """Test config with multiple server instances."""
        config = MinecraftConfig(
            enabled=True,
            announcement_channel_id=123456789,
            servers=[
                MinecraftServerConfig(name="Survival", urls=["mc1.example.com:25565"]),
                MinecraftServerConfig(name="Creative", urls=["mc2.example.com:25565"]),
                MinecraftServerConfig(name="Minigames", urls=["mc3.example.com:25565"]),
            ],
        )
        assert len(config.servers) == 3
        assert config.servers[0].name == "Survival"
        assert config.servers[1].name == "Creative"
        assert config.servers[2].name == "Minigames"


# =============================================================================
# Build Minecraft Schedule Config Tests
# =============================================================================


class TestBuildMinecraftScheduleConfig:
    """Tests for _build_minecraft_schedule_config function."""

    def test_loads_from_json(self) -> None:
        """Test loading schedule config from JSON."""
        schedule_json = {
            "timezone": "Europe/London",
            "health_check_interval_minutes": 2,
            "player_check_interval_seconds": 10,
        }

        with patch.dict(os.environ, {}, clear=True):
            config = _build_minecraft_schedule_config(schedule_json)

        assert config.timezone == "Europe/London"
        assert config.health_check_interval_minutes == 2
        assert config.player_check_interval_seconds == 10

    def test_env_vars_override_json(self) -> None:
        """Test that environment variables override JSON values."""
        schedule_json = {
            "timezone": "Europe/London",
            "health_check_interval_minutes": 2,
            "player_check_interval_seconds": 10,
        }
        env_vars = {
            "MINECRAFT_SCHEDULE_TIMEZONE": "UTC",
            "MINECRAFT_SCHEDULE_HEALTH_CHECK_INTERVAL": "5",
            "MINECRAFT_SCHEDULE_PLAYER_CHECK_INTERVAL": "60",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_minecraft_schedule_config(schedule_json)

        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 5
        assert config.player_check_interval_seconds == 60

    def test_uses_defaults_when_not_specified(self) -> None:
        """Test default values when nothing is specified."""
        with patch.dict(os.environ, {}, clear=True):
            config = _build_minecraft_schedule_config({})

        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 1
        assert config.player_check_interval_seconds == 30


# =============================================================================
# Build Minecraft Server Config Tests
# =============================================================================


class TestBuildMinecraftServerConfig:
    """Tests for _build_minecraft_server_config function."""

    def test_loads_server_with_urls_list(self) -> None:
        """Test loading server config with urls list."""
        server_json = {
            "name": "Survival",
            "urls": ["mc.example.com:25565", "backup.local:25565"],
        }

        config = _build_minecraft_server_config(server_json)

        assert config.name == "Survival"
        assert config.urls == ["mc.example.com:25565", "backup.local:25565"]

    def test_loads_server_with_single_url(self) -> None:
        """Test loading server config with single url string."""
        server_json = {
            "name": "Creative",
            "url": "mc.example.com:25565",
        }

        config = _build_minecraft_server_config(server_json)

        assert config.name == "Creative"
        assert config.urls == ["mc.example.com:25565"]

    def test_missing_name_raises_error(self) -> None:
        """Test that missing name raises ConfigurationError."""
        server_json = {"urls": ["localhost:25565"]}

        with pytest.raises(ConfigurationError) as exc_info:
            _build_minecraft_server_config(server_json)

        assert "must have a 'name' field" in str(exc_info.value)

    def test_missing_urls_raises_error(self) -> None:
        """Test that missing urls raises ConfigurationError."""
        server_json = {"name": "Survival"}

        with pytest.raises(ConfigurationError) as exc_info:
            _build_minecraft_server_config(server_json)

        assert "must have 'urls'" in str(exc_info.value)


# =============================================================================
# Build Minecraft Config Tests
# =============================================================================


class TestBuildMinecraftConfig:
    """Tests for _build_minecraft_config function."""

    def test_loads_complete_config_from_json(self) -> None:
        """Test loading complete Minecraft config from JSON."""
        json_config = {
            "minecraft": {
                "enabled": True,
                "announcement_channel_id": 123456789,
                "alert_channel_id": 987654321,
                "servers": [
                    {
                        "name": "Survival",
                        "urls": ["mc.example.com:25565"],
                    }
                ],
                "schedule": {
                    "timezone": "UTC",
                    "health_check_interval_minutes": 2,
                    "player_check_interval_seconds": 15,
                },
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            config = _build_minecraft_config(json_config)

        assert config.enabled is True
        assert config.announcement_channel_id == 123456789
        assert config.alert_channel_id == 987654321
        assert len(config.servers) == 1
        assert config.servers[0].name == "Survival"
        assert config.schedule.timezone == "UTC"

    def test_disabled_by_default(self) -> None:
        """Test that Minecraft is disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            config = _build_minecraft_config({})

        assert config.enabled is False

    def test_env_vars_override_channel_ids(self) -> None:
        """Test that environment variables override channel IDs."""
        json_config = {
            "minecraft": {
                "enabled": True,
                "announcement_channel_id": 111,
                "alert_channel_id": 222,
                "servers": [{"name": "Test", "urls": ["localhost:25565"]}],
            }
        }
        env_vars = {
            "MINECRAFT_ANNOUNCEMENT_CHANNEL_ID": "999",
            "MINECRAFT_ALERT_CHANNEL_ID": "888",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_minecraft_config(json_config)

        assert config.announcement_channel_id == 999
        assert config.alert_channel_id == 888

    def test_enabled_without_channel_raises_error(self) -> None:
        """Test that enabling without channel ID raises error."""
        json_config = {
            "minecraft": {
                "enabled": True,
                "servers": [{"name": "Test", "urls": ["localhost:25565"]}],
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_minecraft_config(json_config)

        assert "announcement channel ID is required" in str(exc_info.value)

    def test_enabled_without_servers_raises_error(self) -> None:
        """Test that enabling without servers raises error."""
        json_config = {
            "minecraft": {
                "enabled": True,
                "announcement_channel_id": 123456789,
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_minecraft_config(json_config)

        assert "At least one Minecraft server must be configured" in str(exc_info.value)

    def test_enabled_via_env(self) -> None:
        """Test enabling Minecraft via environment variable."""
        json_config = {
            "minecraft": {
                "announcement_channel_id": 123456789,
                "servers": [{"name": "Test", "urls": ["localhost:25565"]}],
            }
        }
        env_vars = {"MINECRAFT_ENABLED": "true"}

        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_minecraft_config(json_config)

        assert config.enabled is True

    def test_multiple_servers(self) -> None:
        """Test loading config with multiple servers."""
        json_config = {
            "minecraft": {
                "enabled": True,
                "announcement_channel_id": 123456789,
                "servers": [
                    {"name": "Survival", "urls": ["mc1.example.com:25565"]},
                    {"name": "Creative", "urls": ["mc2.example.com:25565"]},
                    {"name": "Minigames", "urls": ["mc3.example.com:25565", "backup:25565"]},
                ],
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            config = _build_minecraft_config(json_config)

        assert len(config.servers) == 3
        assert config.servers[0].name == "Survival"
        assert config.servers[1].name == "Creative"
        assert config.servers[2].name == "Minigames"
        assert len(config.servers[2].urls) == 2


# =============================================================================
# Load Config with Minecraft Tests
# =============================================================================


class TestLoadConfigWithMinecraft:
    """Tests for load_config function including Minecraft configuration."""

    def test_loads_minecraft_from_json(
        self, temp_config_file: Path, config_json: dict[str, Any]
    ) -> None:
        """Test that Minecraft config is loaded from JSON file."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config(temp_config_file)

        assert config.minecraft.enabled == config_json["minecraft"]["enabled"]
        assert (
            config.minecraft.announcement_channel_id
            == config_json["minecraft"]["announcement_channel_id"]
        )
        assert len(config.minecraft.servers) == 2
        assert config.minecraft.servers[0].name == "Survival"

    def test_minecraft_disabled_in_minimal_config(self, tmp_path: Path) -> None:
        """Test that Minecraft is disabled when not in config."""
        minimal_json = {
            "discord": {
                "token": "test-token",
                "announcement_channel_id": 123456789,
            },
            "jellyfin": {
                "url": "http://localhost:8096",
                "api_key": "test-key",
            },
        }
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump(minimal_json, f)

        with patch.dict(os.environ, {}, clear=True):
            config = load_config(config_path)

        assert config.minecraft.enabled is False
        assert config.minecraft.servers == []

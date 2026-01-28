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
    Config,
    ConfigurationError,
    DiscordConfig,
    JellyfinConfig,
    ScheduleConfig,
    load_config,
    _get_env,
    _get_env_int,
    _get_env_list,
    _load_json_config,
    _build_discord_config,
    _build_jellyfin_config,
    _build_schedule_config,
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


class TestJellyfinConfig:
    """Tests for JellyfinConfig dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating JellyfinConfig with required fields."""
        config = JellyfinConfig(
            url="http://localhost:8096",
            api_key="test-api-key",
        )
        assert config.url == "http://localhost:8096"
        assert config.api_key == "test-api-key"

    def test_trailing_slash_removed(self) -> None:
        """Test that trailing slashes are removed from URL."""
        config = JellyfinConfig(
            url="http://localhost:8096/",
            api_key="test-api-key",
        )
        assert config.url == "http://localhost:8096"

    def test_multiple_trailing_slashes_removed(self) -> None:
        """Test that multiple trailing slashes are removed."""
        config = JellyfinConfig(
            url="http://localhost:8096///",
            api_key="test-api-key",
        )
        assert config.url == "http://localhost:8096"


class TestScheduleConfig:
    """Tests for ScheduleConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values for schedule config."""
        config = ScheduleConfig()
        assert config.announcement_times == ["17:00"]
        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 5
        assert config.lookback_hours == 24
        assert config.max_items_per_type == 10

    def test_custom_values(self) -> None:
        """Test custom values for schedule config."""
        config = ScheduleConfig(
            announcement_times=["09:00", "21:00"],
            timezone="UTC",
            health_check_interval_minutes=10,
            lookback_hours=48,
            max_items_per_type=5,
        )
        assert config.announcement_times == ["09:00", "21:00"]
        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 10
        assert config.lookback_hours == 48
        assert config.max_items_per_type == 5


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


class TestBuildJellyfinConfig:
    """Tests for _build_jellyfin_config function."""

    def test_loads_from_json(self) -> None:
        """Test loading Jellyfin config from JSON."""
        json_config = {
            "jellyfin": {
                "url": "http://test:8096",
                "api_key": "test-key",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_jellyfin_config(json_config)
        assert config.url == "http://test:8096"
        assert config.api_key == "test-key"

    def test_env_overrides_json(self) -> None:
        """Test environment variables override JSON values."""
        json_config = {
            "jellyfin": {
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

    def test_raises_on_missing_url(self) -> None:
        """Test raising error when URL is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_jellyfin_config({})
            assert "Jellyfin URL is required" in str(exc_info.value)

    def test_raises_on_missing_api_key(self) -> None:
        """Test raising error when API key is missing."""
        json_config = {"jellyfin": {"url": "http://test:8096"}}
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                _build_jellyfin_config(json_config)
            assert "Jellyfin API key is required" in str(exc_info.value)


class TestBuildScheduleConfig:
    """Tests for _build_schedule_config function."""

    def test_uses_defaults(self) -> None:
        """Test using default values when nothing is configured."""
        with patch.dict(os.environ, {}, clear=True):
            config = _build_schedule_config({})
        assert config.announcement_times == ["17:00"]
        assert config.timezone == "America/Los_Angeles"
        assert config.health_check_interval_minutes == 5
        assert config.lookback_hours == 24

    def test_loads_from_json(self) -> None:
        """Test loading schedule config from JSON."""
        json_config = {
            "schedule": {
                "announcement_times": ["09:00", "21:00"],
                "timezone": "UTC",
                "health_check_interval_minutes": 10,
                "lookback_hours": 48,
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            config = _build_schedule_config(json_config)
        assert config.announcement_times == ["09:00", "21:00"]
        assert config.timezone == "UTC"
        assert config.health_check_interval_minutes == 10
        assert config.lookback_hours == 48

    def test_env_overrides_json(self) -> None:
        """Test environment variables override JSON values."""
        json_config = {
            "schedule": {
                "announcement_times": ["12:00"],
                "timezone": "UTC",
            }
        }
        env_vars = {
            "SCHEDULE_ANNOUNCEMENT_TIMES": "06:00,18:00",
            "SCHEDULE_TIMEZONE": "Europe/London",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = _build_schedule_config(json_config)
        assert config.announcement_times == ["06:00", "18:00"]
        assert config.timezone == "Europe/London"


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
        assert config.jellyfin.url == config_json["jellyfin"]["url"]
        assert config.jellyfin.api_key == config_json["jellyfin"]["api_key"]
        assert (
            config.schedule.announcement_times
            == config_json["schedule"]["announcement_times"]
        )
        assert config.content_types == config_json["content_types"]

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

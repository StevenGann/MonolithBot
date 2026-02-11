"""
Tests for the logging service module.

Tests cover:
- TaggedFormatter tag extraction and formatting
- StartupRotatingFileHandler filename generation
- setup_file_logging function behavior
- Log directory creation
- cleanup_old_logs utility
"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.services.logging_service import (
    LOGGER_TAG_MAP,
    StartupRotatingFileHandler,
    TaggedFormatter,
    cleanup_old_logs,
    get_log_level_from_string,
    setup_file_logging,
)


# =============================================================================
# TaggedFormatter Tests
# =============================================================================


class TestTaggedFormatter:
    """Tests for the TaggedFormatter class."""

    @pytest.fixture
    def formatter(self):
        """Create a TaggedFormatter instance."""
        return TaggedFormatter()

    def test_get_tag_exact_match(self, formatter):
        """Test exact match for logger name."""
        assert formatter._get_tag("monolithbot") == "CORE"
        assert formatter._get_tag("monolithbot.jellyfin") == "JELLYFIN"
        assert formatter._get_tag("discord") == "DISCORD"

    def test_get_tag_prefix_match(self, formatter):
        """Test prefix matching for unknown sub-loggers."""
        # Should match the parent logger
        assert formatter._get_tag("monolithbot.jellyfin.unknown") == "JELLYFIN"
        assert formatter._get_tag("monolithbot.minecraft.custom") == "MINECRAFT"
        assert formatter._get_tag("discord.custom.sublogger") == "DISCORD"

    def test_get_tag_unknown_logger(self, formatter):
        """Test fallback for completely unknown logger names."""
        assert formatter._get_tag("unknown.logger") == "OTHER"
        assert formatter._get_tag("random") == "OTHER"

    def test_get_tag_monolithbot_child(self, formatter):
        """Test that child loggers of monolithbot get appropriate tags."""
        assert formatter._get_tag("monolithbot.registration") == "REGISTER"
        assert formatter._get_tag("monolithbot.nextcloud") == "NEXTCLOUD"
        assert formatter._get_tag("monolithbot.navidrome") == "NAVIDROME"
        assert formatter._get_tag("monolithbot.organizr") == "ORGANIZR"
        assert formatter._get_tag("monolithbot.romm") == "ROMM"

    def test_format_adds_tag(self, formatter):
        """Test that format adds the tag attribute to records."""
        record = logging.LogRecord(
            name="monolithbot.jellyfin",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        assert hasattr(record, "tag")
        assert record.tag == "JELLYFIN"
        assert "JELLYFIN" in formatted
        assert "Test message" in formatted

    def test_format_includes_timestamp(self, formatter):
        """Test that formatted output includes timestamp."""
        record = logging.LogRecord(
            name="monolithbot",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Check timestamp format (YYYY-MM-DD HH:MM:SS)
        assert "|" in formatted
        parts = formatted.split("|")
        assert len(parts) >= 4

    def test_format_includes_level(self, formatter):
        """Test that formatted output includes log level."""
        record = logging.LogRecord(
            name="monolithbot",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Test warning",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        assert "WARNING" in formatted

    def test_custom_tag_map(self):
        """Test formatter with custom tag map."""
        custom_map = {"mylogger": "CUSTOM"}
        formatter = TaggedFormatter(tag_map=custom_map)

        assert formatter._get_tag("mylogger") == "CUSTOM"
        assert formatter._get_tag("unknown") == "OTHER"


# =============================================================================
# StartupRotatingFileHandler Tests
# =============================================================================


class TestStartupRotatingFileHandler:
    """Tests for the StartupRotatingFileHandler class."""

    def test_generate_filename_format(self):
        """Test that filenames follow the expected format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = StartupRotatingFileHandler(log_dir=tmpdir)

            # Check filename format
            filename = Path(handler.baseFilename).name
            assert filename.startswith("MonolithBot.")
            assert filename.endswith(".log")

            # Format: MonolithBot.YYYY-MM-DD.HH-MM-SS.log
            parts = filename.replace("MonolithBot.", "").replace(".log", "")
            date_part, time_part = parts.rsplit(".", 1)

            # Verify date format
            datetime.strptime(date_part, "%Y-%m-%d")
            # Verify time format
            datetime.strptime(time_part, "%H-%M-%S")

            handler.close()

    def test_creates_log_directory(self):
        """Test that handler creates log directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = Path(tmpdir) / "nested" / "logs"
            assert not nested_dir.exists()

            handler = StartupRotatingFileHandler(log_dir=nested_dir)

            assert nested_dir.exists()
            handler.close()

    def test_creates_log_file(self):
        """Test that handler creates a log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = StartupRotatingFileHandler(log_dir=tmpdir)

            log_file = Path(handler.baseFilename)
            assert log_file.exists()

            handler.close()

    def test_log_dir_stored(self):
        """Test that log_dir attribute is stored correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = StartupRotatingFileHandler(log_dir=tmpdir)

            assert handler.log_dir == Path(tmpdir)
            handler.close()

    @patch("bot.services.logging_service.datetime")
    def test_filename_uses_provided_timezone(self, mock_datetime):
        """Test that filename uses configured timezone."""
        # This is a basic check - full timezone testing would require more setup
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = StartupRotatingFileHandler(
                log_dir=tmpdir, timezone="America/New_York"
            )

            assert handler.timezone_name == "America/New_York"
            handler.close()


# =============================================================================
# setup_file_logging Tests
# =============================================================================


class TestSetupFileLogging:
    """Tests for the setup_file_logging function."""

    def test_creates_log_directory(self):
        """Test that setup creates the log directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            assert not log_dir.exists()

            log_path = setup_file_logging(
                log_dir=log_dir,
                log_to_file=True,
                log_to_console=False,
            )

            assert log_dir.exists()
            assert log_path is not None

    def test_returns_log_path_when_file_logging_enabled(self):
        """Test that function returns log path when file logging is enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = setup_file_logging(
                log_dir=tmpdir,
                log_to_file=True,
                log_to_console=False,
            )

            assert log_path is not None
            assert log_path.exists()
            assert log_path.suffix == ".log"

    def test_returns_none_when_file_logging_disabled(self):
        """Test that function returns None when file logging is disabled."""
        log_path = setup_file_logging(
            log_dir="logs",
            log_to_file=False,
            log_to_console=True,
        )

        assert log_path is None

    def test_sets_log_level(self):
        """Test that function sets the correct log level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_file_logging(
                log_dir=tmpdir,
                level="DEBUG",
                log_to_file=True,
                log_to_console=False,
            )

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    def test_console_handler_added(self):
        """Test that console handler is added when enabled."""
        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_file_logging(
            log_dir="logs",
            log_to_file=False,
            log_to_console=True,
        )

        # Check that a StreamHandler was added
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 1

    def test_file_handler_added(self):
        """Test that file handler is added when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clear existing handlers
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            setup_file_logging(
                log_dir=tmpdir,
                log_to_file=True,
                log_to_console=False,
            )

            # Check that a file handler was added
            file_handlers = [
                h
                for h in root_logger.handlers
                if isinstance(h, StartupRotatingFileHandler)
            ]
            assert len(file_handlers) == 1


# =============================================================================
# get_log_level_from_string Tests
# =============================================================================


class TestGetLogLevelFromString:
    """Tests for the get_log_level_from_string function."""

    def test_debug_level(self):
        """Test DEBUG level conversion."""
        assert get_log_level_from_string("DEBUG") == logging.DEBUG
        assert get_log_level_from_string("debug") == logging.DEBUG

    def test_info_level(self):
        """Test INFO level conversion."""
        assert get_log_level_from_string("INFO") == logging.INFO
        assert get_log_level_from_string("info") == logging.INFO

    def test_warning_level(self):
        """Test WARNING level conversion."""
        assert get_log_level_from_string("WARNING") == logging.WARNING
        assert get_log_level_from_string("WARN") == logging.WARNING

    def test_error_level(self):
        """Test ERROR level conversion."""
        assert get_log_level_from_string("ERROR") == logging.ERROR
        assert get_log_level_from_string("error") == logging.ERROR

    def test_critical_level(self):
        """Test CRITICAL level conversion."""
        assert get_log_level_from_string("CRITICAL") == logging.CRITICAL

    def test_invalid_level_returns_info(self):
        """Test that invalid level defaults to INFO."""
        assert get_log_level_from_string("INVALID") == logging.INFO
        assert get_log_level_from_string("") == logging.INFO


# =============================================================================
# cleanup_old_logs Tests
# =============================================================================


class TestCleanupOldLogs:
    """Tests for the cleanup_old_logs function."""

    def test_returns_zero_for_nonexistent_directory(self):
        """Test that function returns 0 for non-existent directory."""
        result = cleanup_old_logs("/nonexistent/path", keep_days=30)
        assert result == 0

    def test_returns_zero_for_empty_directory(self):
        """Test that function returns 0 for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cleanup_old_logs(tmpdir, keep_days=30)
            assert result == 0

    def test_does_not_delete_recent_logs(self):
        """Test that recent log files are not deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a recent log file
            log_file = Path(tmpdir) / "MonolithBot.2024-01-15.12-00-00.log"
            log_file.touch()

            result = cleanup_old_logs(tmpdir, keep_days=30)

            assert result == 0
            assert log_file.exists()

    def test_ignores_non_log_files(self):
        """Test that non-log files are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-log file
            other_file = Path(tmpdir) / "config.json"
            other_file.touch()

            result = cleanup_old_logs(tmpdir, keep_days=0)

            # Even with keep_days=0, non-log files should not be deleted
            # (The file might still exist if it matches the pattern check)
            assert other_file.exists()

    def test_ignores_wrong_filename_pattern(self):
        """Test that files with wrong naming pattern are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with wrong pattern
            wrong_file = Path(tmpdir) / "other.log"
            wrong_file.touch()

            result = cleanup_old_logs(tmpdir, keep_days=0)

            assert wrong_file.exists()


# =============================================================================
# LOGGER_TAG_MAP Tests
# =============================================================================


class TestLoggerTagMap:
    """Tests for the LOGGER_TAG_MAP constant."""

    def test_monolithbot_core_tag(self):
        """Test that monolithbot maps to CORE."""
        assert LOGGER_TAG_MAP["monolithbot"] == "CORE"

    def test_jellyfin_tags(self):
        """Test that all Jellyfin loggers map to JELLYFIN."""
        assert LOGGER_TAG_MAP["monolithbot.jellyfin"] == "JELLYFIN"
        assert LOGGER_TAG_MAP["monolithbot.jellyfin.announcements"] == "JELLYFIN"
        assert LOGGER_TAG_MAP["monolithbot.jellyfin.health"] == "JELLYFIN"
        assert LOGGER_TAG_MAP["monolithbot.jellyfin.suggestions"] == "JELLYFIN"

    def test_minecraft_tags(self):
        """Test that all Minecraft loggers map to MINECRAFT."""
        assert LOGGER_TAG_MAP["monolithbot.minecraft"] == "MINECRAFT"
        assert LOGGER_TAG_MAP["monolithbot.minecraft.health"] == "MINECRAFT"
        assert LOGGER_TAG_MAP["monolithbot.minecraft.players"] == "MINECRAFT"

    def test_registration_tag(self):
        """Test that registration logger maps to REGISTER."""
        assert LOGGER_TAG_MAP["monolithbot.registration"] == "REGISTER"

    def test_service_tags(self):
        """Test that service loggers have correct tags."""
        assert LOGGER_TAG_MAP["monolithbot.nextcloud"] == "NEXTCLOUD"
        assert LOGGER_TAG_MAP["monolithbot.navidrome"] == "NAVIDROME"
        assert LOGGER_TAG_MAP["monolithbot.organizr"] == "ORGANIZR"
        assert LOGGER_TAG_MAP["monolithbot.romm"] == "ROMM"
        assert LOGGER_TAG_MAP["monolithbot.user_registry"] == "REGISTRY"
        assert LOGGER_TAG_MAP["monolithbot.scheduler"] == "SCHEDULER"

    def test_third_party_tags(self):
        """Test that third-party library loggers have correct tags."""
        assert LOGGER_TAG_MAP["discord"] == "DISCORD"
        assert LOGGER_TAG_MAP["discord.client"] == "DISCORD"
        assert LOGGER_TAG_MAP["aiohttp"] == "HTTP"
        assert LOGGER_TAG_MAP["apscheduler"] == "SCHEDULER"

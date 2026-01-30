"""Unit tests for bot/main.py - Bot entry point and CLI.

Tests cover:
    - TestModes dataclass
    - Command-line argument parsing
    - Logging configuration
    - Test mode building
"""

import argparse
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.main import TestModes, build_test_modes, parse_args, setup_logging


# =============================================================================
# TestModes Tests
# =============================================================================


class TestTestModes:
    """Tests for TestModes dataclass."""

    def test_default_all_false(self) -> None:
        """Test that all test modes default to False."""
        modes = TestModes()
        assert modes.jf_health is False
        assert modes.jf_announcement is False
        assert modes.jf_suggestion is False
        assert modes.mc_health is False
        assert modes.mc_announce is False
        assert modes.any_enabled is False

    def test_any_enabled_true(self) -> None:
        """Test any_enabled returns True when any mode is enabled."""
        modes = TestModes(jf_health=True)
        assert modes.any_enabled is True

        modes = TestModes(mc_announce=True)
        assert modes.any_enabled is True

    def test_all_enabled_classmethod(self) -> None:
        """Test all_enabled classmethod sets all modes to True."""
        modes = TestModes.all_enabled()
        assert modes.jf_health is True
        assert modes.jf_announcement is True
        assert modes.jf_suggestion is True
        assert modes.mc_health is True
        assert modes.mc_announce is True
        assert modes.any_enabled is True


# =============================================================================
# Argument Parsing Tests
# =============================================================================


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_config_path(self) -> None:
        """Test that default config path is config.json."""
        with patch("sys.argv", ["bot.main"]):
            args = parse_args()
            assert args.config == Path("config.json")

    def test_custom_config_path(self) -> None:
        """Test that custom config path is parsed."""
        with patch("sys.argv", ["bot.main", "--config", "custom.json"]):
            args = parse_args()
            assert args.config == Path("custom.json")

    def test_verbose_flag(self) -> None:
        """Test that verbose flag is parsed."""
        with patch("sys.argv", ["bot.main", "--verbose"]):
            args = parse_args()
            assert args.verbose is True

    def test_test_flag(self) -> None:
        """Test that test flag is parsed."""
        with patch("sys.argv", ["bot.main", "--test"]):
            args = parse_args()
            assert args.test is True

    def test_test_jellyfin_flag(self) -> None:
        """Test that test-jellyfin flag is parsed."""
        with patch("sys.argv", ["bot.main", "--test-jellyfin"]):
            args = parse_args()
            assert args.test_jellyfin is True

    def test_test_minecraft_flag(self) -> None:
        """Test that test-minecraft flag is parsed."""
        with patch("sys.argv", ["bot.main", "--test-minecraft"]):
            args = parse_args()
            assert args.test_minecraft is True

    def test_specific_test_flags(self) -> None:
        """Test that specific test flags are parsed."""
        with patch(
            "sys.argv",
            [
                "bot.main",
                "--test-jf-health",
                "--test-jf-announcement",
                "--test-mc-health",
            ],
        ):
            args = parse_args()
            assert args.test_jf_health is True
            assert args.test_jf_announcement is True
            assert args.test_mc_health is True


# =============================================================================
# Build Test Modes Tests
# =============================================================================


class TestBuildTestModes:
    """Tests for build_test_modes function."""

    def test_all_enabled_with_test_flag(self) -> None:
        """Test that --test enables all modes."""
        args = argparse.Namespace(
            test=True,
            test_jellyfin=False,
            test_jf_health=False,
            test_jf_announcement=False,
            test_jf_suggestion=False,
            test_minecraft=False,
            test_mc_health=False,
            test_mc_announce=False,
        )
        modes = build_test_modes(args)
        assert modes.jf_health is True
        assert modes.jf_announcement is True
        assert modes.jf_suggestion is True
        assert modes.mc_health is True
        assert modes.mc_announce is True

    def test_jellyfin_all_enabled(self) -> None:
        """Test that --test-jellyfin enables all Jellyfin modes."""
        args = argparse.Namespace(
            test=False,
            test_jellyfin=True,
            test_jf_health=False,
            test_jf_announcement=False,
            test_jf_suggestion=False,
            test_minecraft=False,
            test_mc_health=False,
            test_mc_announce=False,
        )
        modes = build_test_modes(args)
        assert modes.jf_health is True
        assert modes.jf_announcement is True
        assert modes.jf_suggestion is True
        assert modes.mc_health is False
        assert modes.mc_announce is False

    def test_minecraft_all_enabled(self) -> None:
        """Test that --test-minecraft enables all Minecraft modes."""
        args = argparse.Namespace(
            test=False,
            test_jellyfin=False,
            test_jf_health=False,
            test_jf_announcement=False,
            test_jf_suggestion=False,
            test_minecraft=True,
            test_mc_health=False,
            test_mc_announce=False,
        )
        modes = build_test_modes(args)
        assert modes.jf_health is False
        assert modes.jf_announcement is False
        assert modes.jf_suggestion is False
        assert modes.mc_health is True
        assert modes.mc_announce is True

    def test_specific_flags(self) -> None:
        """Test that specific flags work independently."""
        args = argparse.Namespace(
            test=False,
            test_jellyfin=False,
            test_jf_health=True,
            test_jf_announcement=False,
            test_jf_suggestion=False,
            test_minecraft=False,
            test_mc_health=True,
            test_mc_announce=False,
        )
        modes = build_test_modes(args)
        assert modes.jf_health is True
        assert modes.jf_announcement is False
        assert modes.jf_suggestion is False
        assert modes.mc_health is True
        assert modes.mc_announce is False


# =============================================================================
# Logging Setup Tests
# =============================================================================


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_info_level_by_default(self) -> None:
        """Test that logging defaults to INFO level."""
        setup_logging(verbose=False)
        assert logging.getLogger("monolithbot").level == logging.INFO

    def test_debug_level_when_verbose(self) -> None:
        """Test that logging uses DEBUG level when verbose."""
        setup_logging(verbose=True)
        assert logging.getLogger("monolithbot").level == logging.DEBUG

    def test_third_party_loggers_reduced(self) -> None:
        """Test that third-party loggers have reduced verbosity."""
        setup_logging(verbose=False)
        assert logging.getLogger("discord").level == logging.WARNING
        assert logging.getLogger("aiohttp").level == logging.WARNING

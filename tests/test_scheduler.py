"""
Unit tests for bot/services/scheduler.py - APScheduler utilities.

Tests cover:
    - create_scheduler function
    - parse_time function for various time formats
    - Error handling for invalid times
"""

import pytest
from unittest.mock import MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.services.scheduler import create_scheduler, parse_time


# =============================================================================
# parse_time Tests
# =============================================================================


class TestParseTime:
    """Tests for the parse_time function."""

    def test_parse_standard_time(self) -> None:
        """Test parsing standard HH:MM format."""
        hour, minute = parse_time("17:00")
        assert hour == 17
        assert minute == 0

    def test_parse_time_with_leading_zero(self) -> None:
        """Test parsing time with leading zeros."""
        hour, minute = parse_time("09:05")
        assert hour == 9
        assert minute == 5

    def test_parse_midnight(self) -> None:
        """Test parsing midnight."""
        hour, minute = parse_time("00:00")
        assert hour == 0
        assert minute == 0

    def test_parse_end_of_day(self) -> None:
        """Test parsing end of day time."""
        hour, minute = parse_time("23:59")
        assert hour == 23
        assert minute == 59

    def test_parse_single_digit_hour(self) -> None:
        """Test parsing time with single digit hour."""
        hour, minute = parse_time("5:30")
        assert hour == 5
        assert minute == 30

    def test_parse_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        hour, minute = parse_time("  17:30  ")
        assert hour == 17
        assert minute == 30

    def test_invalid_hour_too_high(self) -> None:
        """Test that hour > 23 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("25:00")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_hour_negative(self) -> None:
        """Test that negative hour raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("-1:00")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_minute_too_high(self) -> None:
        """Test that minute > 59 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("12:60")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_minute_negative(self) -> None:
        """Test that negative minute raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("12:-5")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_format_too_many_parts(self) -> None:
        """Test that HH:MM:SS format raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("12:30:00")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_format_no_colon(self) -> None:
        """Test that time without colon raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("1730")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_format_not_numbers(self) -> None:
        """Test that non-numeric values raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("ab:cd")
        assert "Invalid time format" in str(exc_info.value)

    def test_invalid_empty_string(self) -> None:
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_time("")
        assert "Invalid time format" in str(exc_info.value)


# =============================================================================
# create_scheduler Tests
# =============================================================================


class TestCreateScheduler:
    """Tests for the create_scheduler function."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create a mock config object."""
        config = MagicMock()
        config.schedule.timezone = "America/Los_Angeles"
        return config

    def test_creates_asyncio_scheduler(self, mock_config: MagicMock) -> None:
        """Test that an AsyncIOScheduler is created."""
        scheduler = create_scheduler(mock_config)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_scheduler_uses_configured_timezone(self, mock_config: MagicMock) -> None:
        """Test that scheduler uses timezone from config."""
        scheduler = create_scheduler(mock_config)
        # APScheduler may use zoneinfo internally, so compare by key/zone name
        assert str(scheduler.timezone) == "America/Los_Angeles"

    def test_scheduler_uses_utc_timezone(self, mock_config: MagicMock) -> None:
        """Test scheduler with UTC timezone."""
        mock_config.schedule.timezone = "UTC"
        scheduler = create_scheduler(mock_config)
        assert str(scheduler.timezone) == "UTC"

    def test_scheduler_uses_different_timezone(self, mock_config: MagicMock) -> None:
        """Test scheduler with different timezone."""
        mock_config.schedule.timezone = "Europe/London"
        scheduler = create_scheduler(mock_config)
        assert str(scheduler.timezone) == "Europe/London"

    def test_scheduler_not_started(self, mock_config: MagicMock) -> None:
        """Test that scheduler is not auto-started."""
        scheduler = create_scheduler(mock_config)
        assert not scheduler.running

    def test_scheduler_job_defaults_coalesce(self, mock_config: MagicMock) -> None:
        """Test that coalesce is enabled by default."""
        scheduler = create_scheduler(mock_config)
        # Access the job defaults through the scheduler
        assert scheduler._job_defaults.get("coalesce") is True

    def test_scheduler_job_defaults_max_instances(self, mock_config: MagicMock) -> None:
        """Test that max_instances is 1 by default."""
        scheduler = create_scheduler(mock_config)
        assert scheduler._job_defaults.get("max_instances") == 1

    def test_scheduler_job_defaults_misfire_grace(self, mock_config: MagicMock) -> None:
        """Test that misfire_grace_time is 60 seconds."""
        scheduler = create_scheduler(mock_config)
        assert scheduler._job_defaults.get("misfire_grace_time") == 60


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestSchedulerIntegration:
    """Integration-style tests for scheduler functionality."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create a mock config object."""
        config = MagicMock()
        config.schedule.timezone = "UTC"
        return config

    def test_can_add_job_after_creation(self, mock_config: MagicMock) -> None:
        """Test that jobs can be added to the scheduler."""
        from apscheduler.triggers.cron import CronTrigger

        scheduler = create_scheduler(mock_config)

        def dummy_job() -> None:
            pass

        hour, minute = parse_time("17:00")
        trigger = CronTrigger(hour=hour, minute=minute)

        scheduler.add_job(
            dummy_job,
            trigger=trigger,
            id="test_job",
        )

        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "test_job"

    def test_can_replace_existing_job(self, mock_config: MagicMock) -> None:
        """Test that jobs can be added with replace_existing flag.

        Note: The replace_existing flag is passed to APScheduler and is used
        when the scheduler is running. This test verifies the API works without
        raising an error when adding a job with the same ID.
        """
        from apscheduler.triggers.cron import CronTrigger

        scheduler = create_scheduler(mock_config)

        def dummy_job() -> None:
            pass

        trigger = CronTrigger(hour=17, minute=0)

        # Add initial job
        scheduler.add_job(
            dummy_job,
            trigger=trigger,
            id="replace_test_job",
            replace_existing=True,
        )

        # Verify initial job exists
        initial_job = scheduler.get_job("replace_test_job")
        assert initial_job is not None

        # Adding a job with replace_existing=True should not raise
        new_trigger = CronTrigger(hour=18, minute=30)
        scheduler.add_job(
            dummy_job,
            trigger=new_trigger,
            id="replace_test_job",
            replace_existing=True,
        )

        # Verify a job with this ID still exists
        final_job = scheduler.get_job("replace_test_job")
        assert final_job is not None

    def test_multiple_jobs(self, mock_config: MagicMock) -> None:
        """Test adding multiple jobs."""
        from apscheduler.triggers.cron import CronTrigger

        scheduler = create_scheduler(mock_config)

        def dummy_job() -> None:
            pass

        times = ["09:00", "17:00", "21:00"]

        for time_str in times:
            hour, minute = parse_time(time_str)
            trigger = CronTrigger(hour=hour, minute=minute)
            scheduler.add_job(
                dummy_job,
                trigger=trigger,
                id=f"job_{time_str}",
            )

        jobs = scheduler.get_jobs()
        assert len(jobs) == 3

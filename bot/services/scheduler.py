"""
APScheduler setup and utilities for MonolithBot.

This module provides factory functions and utilities for creating and
configuring APScheduler instances used by the bot's cogs.

APScheduler is used for two types of scheduled tasks:
    1. Content announcements - CronTrigger at specific times (e.g., 17:00 daily)
    2. Health checks - IntervalTrigger every N minutes

Each cog creates its own scheduler instance to maintain independent lifecycles.
This allows cogs to be loaded/unloaded without affecting other scheduled tasks.

Example:
    >>> from bot.services.scheduler import create_scheduler, parse_time
    >>> from apscheduler.triggers.cron import CronTrigger
    >>>
    >>> scheduler = create_scheduler(config)
    >>> hour, minute = parse_time("17:00")
    >>> scheduler.add_job(my_func, CronTrigger(hour=hour, minute=minute))
    >>> scheduler.start()

See Also:
    - APScheduler documentation: https://apscheduler.readthedocs.io/
    - bot.cogs.announcements: Uses CronTrigger for scheduled announcements
    - bot.cogs.health: Uses IntervalTrigger for periodic health checks
"""

import logging
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from bot.config import Config

# Module logger
logger = logging.getLogger("monolithbot.scheduler")


def create_scheduler(config: "Config") -> AsyncIOScheduler:
    """
    Create and configure an AsyncIOScheduler instance.

    Creates a scheduler configured with the timezone from the bot's config
    and sensible defaults for job execution. The scheduler is returned in
    a stopped state - the caller must call `scheduler.start()` when ready.

    Args:
        config: Bot configuration object. Uses `config.schedule.timezone`
            to set the scheduler's timezone for interpreting job times.

    Returns:
        A configured but not-yet-started AsyncIOScheduler instance.

    Job Defaults:
        The scheduler is configured with these job defaults:

        - **coalesce** (True): If multiple executions of a job are missed
          (e.g., bot was offline), only run it once when it comes back.
          This prevents announcement spam after an outage.

        - **max_instances** (1): Only allow one instance of each job to
          run at a time. Prevents overlapping executions if a job runs
          longer than its interval.

        - **misfire_grace_time** (60 seconds): If a job's scheduled time
          is missed by less than 60 seconds, still run it. Jobs missed
          by more than this are skipped (and coalesced if applicable).

    Example:
        >>> scheduler = create_scheduler(config)
        >>> scheduler.add_job(
        ...     my_announcement_func,
        ...     CronTrigger(hour=17, minute=0),
        ...     id="daily_announcement"
        ... )
        >>> scheduler.start()
        >>>
        >>> # Later, to shut down:
        >>> scheduler.shutdown(wait=False)

    Note:
        Each cog should create its own scheduler instance. This ensures
        that unloading a cog properly cleans up its scheduled jobs without
        affecting other cogs.
    """
    # Parse timezone string into pytz timezone object
    timezone = pytz.timezone(config.schedule.timezone)

    scheduler = AsyncIOScheduler(
        timezone=timezone,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        },
    )

    logger.info(f"Created scheduler with timezone: {config.schedule.timezone}")
    return scheduler


def parse_time(time_str: str) -> tuple[int, int]:
    """
    Parse a time string in HH:MM format into hour and minute components.

    This utility function converts user-friendly time strings from the
    configuration into the integer components needed by APScheduler's
    CronTrigger.

    Args:
        time_str: Time string in 24-hour HH:MM format.
            Examples: "17:00", "09:30", "0:00", "23:59"
            Leading/trailing whitespace is stripped.

    Returns:
        A tuple of (hour, minute) as integers.
        - hour: 0-23
        - minute: 0-59

    Raises:
        ValueError: If the time string is malformed or contains invalid values.
            The error message describes the expected format.

    Examples:
        >>> parse_time("17:00")
        (17, 0)

        >>> parse_time("09:30")
        (9, 30)

        >>> parse_time("  21:15  ")  # Whitespace is stripped
        (21, 15)

        >>> parse_time("25:00")  # Invalid hour
        ValueError: Invalid time format '25:00': expected HH:MM

        >>> parse_time("17:00:00")  # Wrong format
        ValueError: Invalid time format '17:00:00': expected HH:MM

    Note:
        This function only validates the time format and value ranges.
        It does not validate that the time makes sense in any particular
        timezone context - that's handled by the scheduler.
    """
    try:
        parts = time_str.strip().split(":")

        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}")

        hour = int(parts[0])
        minute = int(parts[1])

        # Validate ranges
        if not (0 <= hour <= 23):
            raise ValueError(f"Hour must be 0-23, got: {hour}")
        if not (0 <= minute <= 59):
            raise ValueError(f"Minute must be 0-59, got: {minute}")

        return hour, minute

    except (ValueError, IndexError) as e:
        # Re-raise with a user-friendly message
        # Chain the original exception for debugging
        raise ValueError(f"Invalid time format '{time_str}': expected HH:MM") from e

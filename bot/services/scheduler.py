"""
APScheduler setup for MonolithBot.

Provides a configured AsyncIOScheduler for scheduling tasks.
"""

import logging
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from bot.config import Config

logger = logging.getLogger("monolithbot.scheduler")


def create_scheduler(config: "Config") -> AsyncIOScheduler:
    """
    Create and configure the AsyncIOScheduler.

    Args:
        config: Bot configuration containing timezone settings

    Returns:
        Configured AsyncIOScheduler (not started)
    """
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
    Parse a time string in HH:MM format.

    Args:
        time_str: Time string like "17:00" or "9:30"

    Returns:
        Tuple of (hour, minute)

    Raises:
        ValueError: If time string is invalid
    """
    try:
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}")

        hour = int(parts[0])
        minute = int(parts[1])

        if not (0 <= hour <= 23):
            raise ValueError(f"Hour must be 0-23, got: {hour}")
        if not (0 <= minute <= 59):
            raise ValueError(f"Minute must be 0-59, got: {minute}")

        return hour, minute

    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid time format '{time_str}': expected HH:MM") from e

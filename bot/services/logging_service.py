"""
Logging service for MonolithBot.

This module provides a comprehensive file-based logging system with:
- New log file created on each bot startup
- Daily rotation at midnight (timezone-aware)
- Configurable log directory for Docker volume mounting
- Structured log format with timestamp, level, tag, and message

Log Format:
    2024-01-15 17:00:00 | INFO     | CORE       | Bot started successfully

Filename Format:
    MonolithBot.YYYY-MM-DD.HH-MM-SS.log

Example:
    >>> from bot.services.logging_service import setup_file_logging
    >>> setup_file_logging(
    ...     log_dir="logs",
    ...     timezone="America/Los_Angeles",
    ...     level="INFO",
    ...     log_to_console=True,
    ...     log_to_file=True,
    ... )

See Also:
    - bot.config: LoggingConfig dataclass
    - bot.main: setup_logging() integration
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

import pytz

# =============================================================================
# Constants
# =============================================================================

# Default log format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(tag)-10s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Mapping from logger names to human-readable tags
LOGGER_TAG_MAP = {
    "monolithbot": "CORE",
    "monolithbot.jellyfin": "JELLYFIN",
    "monolithbot.jellyfin.announcements": "JELLYFIN",
    "monolithbot.jellyfin.health": "JELLYFIN",
    "monolithbot.jellyfin.suggestions": "JELLYFIN",
    "monolithbot.minecraft": "MINECRAFT",
    "monolithbot.minecraft.health": "MINECRAFT",
    "monolithbot.minecraft.players": "MINECRAFT",
    "monolithbot.registration": "REGISTER",
    "monolithbot.nextcloud": "NEXTCLOUD",
    "monolithbot.navidrome": "NAVIDROME",
    "monolithbot.organizr": "ORGANIZR",
    "monolithbot.romm": "ROMM",
    "monolithbot.user_registry": "REGISTRY",
    "monolithbot.scheduler": "SCHEDULER",
    "discord": "DISCORD",
    "discord.client": "DISCORD",
    "discord.gateway": "DISCORD",
    "discord.http": "DISCORD",
    "aiohttp": "HTTP",
    "apscheduler": "SCHEDULER",
}


# =============================================================================
# Custom Formatter
# =============================================================================


class TaggedFormatter(logging.Formatter):
    """
    Custom formatter that adds a tag field based on the logger name.

    The tag provides a human-readable identifier for the log source,
    making it easier to filter and search logs.

    Attributes:
        tag_map: Dictionary mapping logger names to tag strings.
    """

    def __init__(
        self,
        fmt: str = LOG_FORMAT,
        datefmt: str = DATE_FORMAT,
        tag_map: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Initialize the formatter.

        Args:
            fmt: Log message format string.
            datefmt: Date/time format string.
            tag_map: Optional custom mapping of logger names to tags.
        """
        super().__init__(fmt, datefmt)
        self.tag_map = tag_map or LOGGER_TAG_MAP

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record with the appropriate tag.

        Args:
            record: The log record to format.

        Returns:
            Formatted log string.
        """
        # Find the most specific matching tag
        record.tag = self._get_tag(record.name)
        return super().format(record)

    def _get_tag(self, logger_name: str) -> str:
        """
        Get the tag for a logger name.

        Tries to find the most specific match first, then falls back
        to progressively less specific matches.

        Args:
            logger_name: The name of the logger (e.g., "monolithbot.jellyfin.health")

        Returns:
            The tag string (e.g., "JELLYFIN")
        """
        # Try exact match first
        if logger_name in self.tag_map:
            return self.tag_map[logger_name]

        # Try progressively shorter prefixes
        parts = logger_name.split(".")
        while parts:
            prefix = ".".join(parts)
            if prefix in self.tag_map:
                return self.tag_map[prefix]
            parts.pop()

        # Default tag for unknown loggers
        return "OTHER"


# =============================================================================
# Custom File Handler
# =============================================================================


class StartupRotatingFileHandler(TimedRotatingFileHandler):
    """
    File handler that creates a new timestamped log file on initialization
    and rotates at midnight.

    This handler:
    - Creates a new log file with timestamp when the handler is created
    - Rotates to a new file at midnight in the configured timezone
    - Uses the naming format: MonolithBot.YYYY-MM-DD.HH-MM-SS.log

    Attributes:
        log_dir: Directory where log files are stored.
        timezone: Timezone for determining midnight rotation.
    """

    def __init__(
        self,
        log_dir: str | Path,
        timezone: str = "UTC",
        level: int = logging.INFO,
    ) -> None:
        """
        Initialize the handler.

        Args:
            log_dir: Directory to store log files.
            timezone: IANA timezone name for midnight rotation.
            level: Minimum log level to record.
        """
        self.log_dir = Path(log_dir)
        self.timezone_name = timezone

        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Generate initial filename with startup timestamp
        self._startup_time = datetime.now(pytz.timezone(timezone))
        initial_filename = self._generate_filename(self._startup_time)
        filepath = self.log_dir / initial_filename

        # Initialize parent class with midnight rotation
        super().__init__(
            filename=str(filepath),
            when="midnight",
            interval=1,
            backupCount=0,  # Keep all logs (no automatic deletion)
            encoding="utf-8",
            utc=False,  # Use local timezone for rotation
        )

        self.setLevel(level)

        # Set up the timezone-aware rotation
        try:
            self.tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError:
            self.tz = pytz.UTC

    def _generate_filename(self, dt: datetime) -> str:
        """
        Generate a log filename for the given datetime.

        Args:
            dt: Datetime to use for the filename.

        Returns:
            Filename in format: MonolithBot.YYYY-MM-DD.HH-MM-SS.log
        """
        return f"MonolithBot.{dt.strftime('%Y-%m-%d.%H-%M-%S')}.log"

    def doRollover(self) -> None:
        """
        Perform log rotation at midnight.

        Creates a new log file with a fresh timestamp.
        """
        # Close current stream
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]

        # Generate new filename with current time
        now = datetime.now(self.tz)
        new_filename = self._generate_filename(now)
        self.baseFilename = str(self.log_dir / new_filename)

        # Open new file
        if not self.delay:
            self.stream = self._open()

        # Compute next rollover time
        self.rolloverAt = self.computeRollover(int(now.timestamp()))


# =============================================================================
# Setup Functions
# =============================================================================


def setup_file_logging(
    log_dir: str | Path = "logs",
    timezone: str = "UTC",
    level: str = "INFO",
    log_to_console: bool = True,
    log_to_file: bool = True,
) -> Optional[Path]:
    """
    Configure the logging system with file and console handlers.

    Sets up:
    - File handler with startup timestamp and midnight rotation
    - Console handler for terminal output
    - Custom formatter with tags for easy filtering

    Args:
        log_dir: Directory for log files. Created if it doesn't exist.
        timezone: IANA timezone name for log timestamps and rotation.
        level: Log level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_to_console: Whether to also log to stdout.
        log_to_file: Whether to write to log files.

    Returns:
        Path to the created log file, or None if file logging is disabled.

    Example:
        >>> log_path = setup_file_logging(
        ...     log_dir="/app/logs",
        ...     timezone="America/Los_Angeles",
        ...     level="DEBUG",
        ... )
        >>> print(f"Logging to: {log_path}")
    """
    # Convert level string to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create formatter
    formatter = TaggedFormatter()

    log_filepath: Optional[Path] = None

    # Set up file handler
    if log_to_file:
        file_handler = StartupRotatingFileHandler(
            log_dir=log_dir,
            timezone=timezone,
            level=numeric_level,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        log_filepath = Path(file_handler.baseFilename)

    # Set up console handler
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Configure third-party library log levels
    _configure_library_loggers()

    return log_filepath


def _configure_library_loggers() -> None:
    """
    Configure log levels for third-party libraries to reduce noise.

    Sets appropriate levels for discord.py, aiohttp, and APScheduler
    to avoid flooding logs with debug/info messages from libraries.
    """
    # Discord.py - only show warnings and above
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)

    # aiohttp - only show warnings
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # APScheduler - show info level (for job execution info)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)


def get_log_level_from_string(level_str: str) -> int:
    """
    Convert a log level string to its numeric value.

    Args:
        level_str: Level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        Numeric log level value.
    """
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_str.upper(), logging.INFO)


def cleanup_old_logs(log_dir: str | Path, keep_days: int = 30) -> int:
    """
    Remove log files older than the specified number of days.

    This is a utility function that can be called periodically
    to manage disk space.

    Args:
        log_dir: Directory containing log files.
        keep_days: Number of days of logs to retain.

    Returns:
        Number of files deleted.
    """
    log_path = Path(log_dir)
    if not log_path.exists():
        return 0

    deleted_count = 0
    cutoff = datetime.now().timestamp() - (keep_days * 86400)

    # Match our log filename pattern
    pattern = re.compile(r"^MonolithBot\.\d{4}-\d{2}-\d{2}\.\d{2}-\d{2}-\d{2}\.log$")

    for file in log_path.iterdir():
        if file.is_file() and pattern.match(file.name):
            if file.stat().st_mtime < cutoff:
                try:
                    file.unlink()
                    deleted_count += 1
                except OSError:
                    pass  # Skip files that can't be deleted

    return deleted_count

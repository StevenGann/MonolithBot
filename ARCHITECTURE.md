# MonolithBot Architecture & Development Guide

This document provides a comprehensive overview of the MonolithBot codebase for developers (human or AI) who need to understand, maintain, or extend the project.

## Table of Contents

- [Project Overview](#project-overview)
- [Directory Structure](#directory-structure)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Configuration System](#configuration-system)
- [Extending the Bot](#extending-the-bot)
- [Key Design Decisions](#key-design-decisions)

---

## Project Overview

MonolithBot is a Discord bot designed to monitor a Jellyfin media server. It provides two primary functions:

1. **Content Announcements**: At scheduled times, announce newly added media (movies, TV shows, music) to a Discord channel with rich embeds
2. **Health Monitoring**: Continuously monitor the Jellyfin server and alert users when it goes offline or comes back online

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Discord API | `discord.py` (v2.3+) | Bot framework, slash commands, embeds |
| HTTP Client | `aiohttp` | Async requests to Jellyfin API |
| Scheduling | `APScheduler` | Cron-based announcements, interval-based health checks |
| Timezone | `pytz` | Timezone-aware scheduling |
| Config | JSON + env vars | Flexible configuration for dev/prod |

---

## Directory Structure

```
MonolithBot/
├── bot/                          # Main application package
│   ├── __init__.py               # Package marker, version info
│   ├── main.py                   # Entry point, CLI, bot initialization
│   ├── config.py                 # Configuration loading and validation
│   ├── cogs/                     # Discord.py cogs (feature modules)
│   │   ├── __init__.py
│   │   ├── announcements.py      # Scheduled content announcements
│   │   └── health.py             # Server health monitoring
│   └── services/                 # External service integrations
│       ├── __init__.py
│       ├── jellyfin.py           # Jellyfin API client
│       └── scheduler.py          # APScheduler factory and utilities
├── .github/
│   └── workflows/
│       └── docker-publish.yml    # CI/CD for Docker image
├── config.json.example           # Example JSON configuration
├── .env.example                  # Example environment variables
├── docker-compose.yml            # Production deployment (pulls from GHCR)
├── docker-compose.local.yml      # Local development (builds from source)
├── Dockerfile                    # Container image definition
├── requirements.txt              # Python dependencies
├── README.md                     # User documentation
└── ARCHITECTURE.md               # This file
```

---

## Core Components

### 1. Entry Point (`bot/main.py`)

The main module handles:

- **CLI argument parsing**: `--config` for custom config path, `--verbose` for debug logging
- **Bot initialization**: Creates `MonolithBot` instance with proper Discord intents
- **Cog loading**: Automatically loads all cogs from `bot/cogs/`
- **Graceful shutdown**: Handles SIGINT/SIGTERM signals

```python
# Key class
class MonolithBot(commands.Bot):
    def __init__(self, config: Config):
        self.config = config  # Config available to all cogs via self.bot.config
```

**Run with**: `python -m bot.main` or `python -m bot.main --config ./myconfig.json`

### 2. Configuration (`bot/config.py`)

The configuration system uses dataclasses for type safety:

```python
@dataclass
class Config:
    discord: DiscordConfig      # token, channel IDs
    jellyfin: JellyfinConfig    # url, api_key
    schedule: ScheduleConfig    # times, timezone, intervals
    content_types: list[str]    # ["Movie", "Series", "Audio"]
```

**Loading priority**: Environment variables override JSON file values. This allows the same codebase to work for local development (JSON) and Docker deployment (env vars).

```python
config = load_config(Path("config.json"))
# 1. Load from JSON file (if exists)
# 2. Override with environment variables (if set)
# 3. Validate required fields
```

### 3. Jellyfin Client (`bot/services/jellyfin.py`)

Async HTTP client for Jellyfin API:

```python
class JellyfinClient:
    async def check_health() -> ServerInfo          # GET /System/Info
    async def get_recent_items(type, hours) -> list[JellyfinItem]  # GET /Items
    def get_item_image_url(item_id) -> str          # Build image URL
    def get_item_url(item_id) -> str                # Build web player URL
```

**Key data classes**:
- `JellyfinItem`: Represents a media item (movie, episode, song)
- `ServerInfo`: Server name, version, OS

**Error hierarchy**:
- `JellyfinError`: Base exception
- `JellyfinConnectionError`: Server unreachable
- `JellyfinAuthError`: Invalid API key

### 4. Announcements Cog (`bot/cogs/announcements.py`)

Handles scheduled content announcements:

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   APScheduler   │────▶│ _run_        │────▶│ Jellyfin    │
│   (CronTrigger) │     │ announcement │     │ API         │
└─────────────────┘     └──────────────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │ Discord      │
                        │ Embeds       │
                        └──────────────┘
```

**Scheduled jobs**: Created from `config.schedule.announcement_times` (e.g., `["17:00", "21:00"]`)

**Slash commands**:
- `/status` - Show bot and Jellyfin status (everyone)
- `/announce` - Manually trigger announcement (admin only)

### 5. Health Cog (`bot/cogs/health.py`)

Monitors Jellyfin server availability:

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   APScheduler   │────▶│ _run_        │────▶│ Jellyfin    │
│ (IntervalTrigger│     │ health_check │     │ check_health│
│  every N mins)  │     └──────────────┘     └─────────────┘
└─────────────────┘            │
                               ▼
                        ┌──────────────┐
                        │ State        │
                        │ Transition?  │
                        └──────────────┘
                          │         │
                    ┌─────┘         └─────┐
                    ▼                     ▼
             ┌────────────┐        ┌────────────┐
             │ Online     │        │ Offline    │
             │ Notification│       │ Notification│
             └────────────┘        └────────────┘
```

**State tracking**: Only sends notifications on state *transitions* (online→offline, offline→online), not on every check.

### 6. Scheduler (`bot/services/scheduler.py`)

Factory function for creating configured `AsyncIOScheduler`:

```python
def create_scheduler(config: Config) -> AsyncIOScheduler:
    # Configured with timezone from config
    # Job defaults: coalesce=True, max_instances=1
```

Utility function `parse_time("17:00")` returns `(17, 0)` tuple for cron triggers.

---

## Data Flow

### Startup Sequence

```
1. main.py: Parse CLI args
2. main.py: load_config() → Config object
3. main.py: Create MonolithBot(config)
4. MonolithBot.setup_hook():
   ├── Load announcements cog
   │   ├── Create JellyfinClient
   │   ├── Create scheduler
   │   ├── Schedule announcement jobs
   │   └── Start scheduler
   └── Load health cog
       ├── Create JellyfinClient
       ├── Create scheduler
       ├── Initial health check
       ├── Schedule health check job
       └── Start scheduler
5. MonolithBot.on_ready(): Log connection info
6. Bot runs until shutdown signal
```

### Announcement Flow

```
1. Scheduler triggers at configured time (e.g., 17:00 PST)
2. _run_announcement() called
3. JellyfinClient.get_all_recent_items() fetches new content
4. For each content type with items:
   a. Send section header embed
   b. For each item (max 10):
      - Create embed with title, description, thumbnail, link
      - Send to announcement channel
5. Update _last_announcement timestamp
```

### Health Check Flow

```
1. Scheduler triggers every N minutes
2. _run_health_check() called
3. JellyfinClient.check_health() attempts connection
4. Compare result to previous state (_server_online)
5. If state changed:
   - online→offline: Send red "Server Offline" embed
   - offline→online: Send green "Server Online" embed with downtime
6. Update state tracking variables
```

---

## Configuration System

### JSON Configuration (`config.json`)

```json
{
  "discord": {
    "token": "BOT_TOKEN",
    "announcement_channel_id": 123456789,
    "alert_channel_id": 123456789
  },
  "jellyfin": {
    "url": "http://localhost:8096",
    "api_key": "API_KEY"
  },
  "schedule": {
    "announcement_times": ["17:00"],
    "timezone": "America/Los_Angeles",
    "health_check_interval_minutes": 5,
    "lookback_hours": 24
  },
  "content_types": ["Movie", "Series", "Audio"]
}
```

### Environment Variables

| Variable | Maps To |
|----------|---------|
| `DISCORD_TOKEN` | `discord.token` |
| `DISCORD_ANNOUNCEMENT_CHANNEL_ID` | `discord.announcement_channel_id` |
| `DISCORD_ALERT_CHANNEL_ID` | `discord.alert_channel_id` |
| `JELLYFIN_URL` | `jellyfin.url` |
| `JELLYFIN_API_KEY` | `jellyfin.api_key` |
| `SCHEDULE_ANNOUNCEMENT_TIMES` | `schedule.announcement_times` (comma-separated) |
| `SCHEDULE_TIMEZONE` | `schedule.timezone` |
| `SCHEDULE_HEALTH_CHECK_INTERVAL` | `schedule.health_check_interval_minutes` |
| `SCHEDULE_LOOKBACK_HOURS` | `schedule.lookback_hours` |
| `CONTENT_TYPES` | `content_types` (comma-separated) |

---

## Extending the Bot

### Adding a New Cog

1. Create `bot/cogs/mycog.py`:

```python
import logging
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from bot.main import MonolithBot

logger = logging.getLogger("monolithbot.mycog")

class MyCog(commands.Cog, name="MyCog"):
    def __init__(self, bot: "MonolithBot"):
        self.bot = bot
        # Access config: self.bot.config

    async def cog_load(self) -> None:
        """Called when cog is loaded. Initialize resources here."""
        logger.info("MyCog loaded")

    async def cog_unload(self) -> None:
        """Called when cog is unloaded. Cleanup resources here."""
        logger.info("MyCog unloaded")

async def setup(bot: "MonolithBot") -> None:
    await bot.add_cog(MyCog(bot))
```

2. Add to cog list in `bot/main.py`:

```python
cogs_to_load = [
    "bot.cogs.announcements",
    "bot.cogs.health",
    "bot.cogs.mycog",  # Add here
]
```

### Adding a New Slash Command

In any cog:

```python
from discord import app_commands

@app_commands.command(name="mycommand", description="Does something")
async def my_command(self, interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Hello!")
```

### Adding New Configuration Options

1. Add to dataclass in `bot/config.py`:

```python
@dataclass
class ScheduleConfig:
    # ... existing fields ...
    my_new_option: int = 10  # With default
```

2. Add environment variable support in `_build_schedule_config()`:

```python
my_new_option = _get_env_int("MY_NEW_OPTION") or schedule_json.get(
    "my_new_option", 10
)
```

3. Update `config.json.example` and `.env.example`

### Adding a New Service

1. Create `bot/services/myservice.py`:

```python
class MyServiceClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self._session = None

    async def close(self):
        if self._session:
            await self._session.close()
```

2. Initialize in the cog that needs it:

```python
async def cog_load(self):
    self.my_service = MyServiceClient(...)

async def cog_unload(self):
    await self.my_service.close()
```

---

## Key Design Decisions

### Why Cogs?

Discord.py's cog pattern provides:
- **Modularity**: Each feature is self-contained
- **Hot reload**: Cogs can be loaded/unloaded without restarting
- **Organization**: Related commands, events, and tasks grouped together

### Why Separate Schedulers per Cog?

Each cog has its own `AsyncIOScheduler` instance because:
- Cogs may be loaded/unloaded independently
- Scheduler lifecycle tied to cog lifecycle
- Avoids shared state issues

### Why Dataclasses for Config?

- **Type safety**: IDE autocomplete and type checking
- **Immutability**: Config shouldn't change at runtime
- **Validation**: `__post_init__` for custom validation logic

### Why Environment Variables Override JSON?

- **Development**: Use `config.json` for easy editing
- **Production**: Use env vars in Docker (no secrets in repo)
- **Flexibility**: Override specific values without copying entire config

### Why State Tracking for Health Checks?

Without state tracking, the bot would send notifications on every failed check (potentially hundreds per day). By tracking `_server_online` state, we only notify on *transitions*, which is the useful signal.

---

## Logging

Loggers follow the pattern `monolithbot.<module>`:

```python
logger = logging.getLogger("monolithbot.announcements")
logger = logging.getLogger("monolithbot.health")
logger = logging.getLogger("monolithbot.jellyfin")
```

Run with `--verbose` for DEBUG level logging.

---

## Testing Locally

1. Copy and edit config:
   ```bash
   cp config.json.example config.json
   ```

2. Run the bot:
   ```bash
   python -m bot.main --verbose
   ```

3. Use `/status` command to verify connectivity

4. Use `/announce` command to test announcements without waiting for schedule

---

## Common Tasks

| Task | Location | Notes |
|------|----------|-------|
| Change announcement embed appearance | `announcements.py` → `_create_item_embed()` | Modify embed fields, colors, etc. |
| Add new content type | `config.py`, `jellyfin.py` → `_map_content_type()` | Map friendly name to Jellyfin type |
| Change health check behavior | `health.py` → `_run_health_check()` | Modify check logic or notifications |
| Add new Jellyfin API call | `jellyfin.py` | Add new async method |
| Add new slash command | Any cog | Use `@app_commands.command` decorator |

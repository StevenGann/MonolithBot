# MonolithBot Architecture & Development Guide

This document provides a comprehensive overview of the MonolithBot codebase for developers (human or AI) who need to understand, maintain, or extend the project. It is the primary reference for onboarding new contributors.

## Table of Contents

- [Project Overview](#project-overview)
- [Directory Structure](#directory-structure)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Configuration System](#configuration-system)
- [Registration System](#registration-system)
- [Extending the Bot](#extending-the-bot)
- [Key Design Decisions](#key-design-decisions)

---

## Project Overview

MonolithBot is a Discord bot with three main feature areas:

1. **Jellyfin Media Server**: Content announcements, random suggestions, and health monitoring
2. **Minecraft Game Servers**: Multi-server health monitoring and player join announcements
3. **Multi-Service User Registration**: One-click registration across Jellyfin, NextCloud, Navidrome, Organizr, and Romm

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Discord API | `discord.py` (v2.3+) | Bot framework, slash commands, embeds, DMs |
| HTTP Client | `aiohttp` | Async requests to external APIs |
| Scheduling | `APScheduler` | Cron-based announcements, interval-based health checks |
| Minecraft Query | `mcstatus` | Server List Ping protocol for Minecraft servers |
| Timezone | `pytz` | Timezone-aware scheduling |
| Config | JSON + env vars | Flexible configuration for dev/prod |

### Directory Structure

```
MonolithBot/
├── bot/                              # Main application package
│   ├── __init__.py                   # Package marker, version info
│   ├── main.py                       # Entry point, CLI, bot initialization
│   ├── config.py                     # Configuration loading and validation
│   ├── cogs/                         # Discord.py cogs (feature modules)
│   │   ├── __init__.py
│   │   ├── jellyfin/                 # Jellyfin-specific cogs
│   │   │   ├── __init__.py
│   │   │   ├── announcements.py      # Scheduled content announcements
│   │   │   ├── health.py             # Jellyfin server health monitoring
│   │   │   └── suggestions.py        # Random content suggestions
│   │   ├── minecraft/                # Minecraft-specific cogs
│   │   │   ├── __init__.py
│   │   │   ├── health.py             # Minecraft server health monitoring
│   │   │   └── players.py            # Player join announcements
│   │   └── registration/             # User registration cogs
│   │       ├── __init__.py
│   │       └── handler.py            # DM handler for registration requests
│   └── services/                     # External service integrations
│       ├── __init__.py
│       ├── jellyfin.py               # Jellyfin API client + service
│       ├── minecraft.py              # Minecraft Server List Ping client + service
│       ├── navidrome.py              # Navidrome API client + service
│       ├── nextcloud.py              # NextCloud OCS API client + service
│       ├── organizr.py               # Organizr v2 API client + service
│       ├── romm.py                   # Romm API client + service
│       ├── registration.py           # Multi-service registration orchestrator
│       ├── password_utils.py         # Secure password generation
│       ├── user_registry.py          # Discord→service account mapping storage
│       └── scheduler.py              # APScheduler factory and utilities
├── tests/                            # Test suite
│   ├── conftest.py                   # Shared pytest fixtures
│   ├── test_config.py                # Configuration tests
│   ├── test_jellyfin.py              # Jellyfin API client tests
│   ├── test_minecraft_service.py     # Minecraft service tests
│   ├── test_minecraft_cogs.py        # Minecraft cog tests
│   ├── test_announcements.py         # Announcements cog tests
│   ├── test_health.py                # Jellyfin health monitoring tests
│   ├── test_suggestions.py           # Suggestions cog tests
│   ├── test_main.py                  # CLI and entry point tests
│   ├── test_scheduler.py             # Scheduler utility tests
│   ├── test_registration.py          # Registration orchestrator tests
│   ├── test_registration_handler.py  # Registration cog tests
│   ├── test_navidrome.py             # Navidrome service tests
│   ├── test_nextcloud.py             # NextCloud service tests
│   ├── test_organizr.py              # Organizr service tests
│   ├── test_romm.py                  # Romm service tests
│   ├── test_password_utils.py        # Password generation tests
│   └── test_user_registry.py         # User registry tests
├── .github/workflows/
│   ├── ci.yml                        # Tests, lint, coverage
│   └── docker-publish.yml            # Docker image build and publish
├── config.json.example               # Example JSON configuration
├── .env.example                      # Example environment variables
├── docker-compose.yml                # Production deployment
├── docker-compose.local.yml          # Local development build
├── Dockerfile                        # Container image definition
├── pyproject.toml                    # Project config, pytest, coverage
├── README.md                         # User documentation
├── ARCHITECTURE.md                   # This file (developer guide)
└── CONTRIBUTING.md                   # Contribution guidelines
```

---

## Core Components

### 1. Entry Point (`bot/main.py`)

The main module handles:

- **CLI argument parsing**: `--config` for custom config path, `--verbose` for debug logging, granular `--test*` flags for each feature
- **Bot initialization**: Creates `MonolithBot` with Discord intents (including `message_content` when registration is enabled)
- **Service initialization**: Creates shared JellyfinService, MinecraftService; registration services are created by the registration cog
- **Cog loading**: Loads cogs conditionally based on config (e.g., Jellyfin cogs only when `jellyfin.enabled=true`)
- **Graceful shutdown**: Handles SIGINT/SIGTERM, closes HTTP sessions
- **Test modes**: Triggers specific features immediately on startup for debugging

**CLI flags**:
| Flag | Short | Description |
|------|-------|-------------|
| `--test` | `-t` | Run all test modes |
| `--test-jellyfin` | | Run all Jellyfin test modes |
| `--test-jf-health` | | Jellyfin health check |
| `--test-jf-announcement` | | Jellyfin content announcement |
| `--test-jf-suggestion` | | Jellyfin random suggestions |
| `--test-minecraft` | | Run all Minecraft test modes |
| `--test-mc-health` | | Minecraft health check |
| `--test-mc-announce` | | Minecraft player announcement |
| `--config` | `-c` | Custom config file path |
| `--verbose` | `-v` | Debug logging |

### 2. Configuration (`bot/config.py`)

Uses dataclasses for type safety. `Config` aggregates: `DiscordConfig`, `JellyfinConfig`, `MinecraftConfig`, plus optional `NextCloudConfig`, `NavidromeConfig`, `OrganizrConfig`, `RommConfig`, and `RegistrationConfig`.

**Loading priority**: Environment variables override JSON file values. Required fields are validated; `ConfigurationError` is raised with clear messages when invalid.

### 3. Service Layer (`bot/services/`)

Each external service follows a consistent pattern:

- **Client**: Low-level HTTP/API client for a single URL (e.g., `JellyfinClient`, `NavidromeClient`)
- **Service**: High-level wrapper with multi-URL failover, cached active URL, and delegated API methods

| Service | Purpose |
|---------|---------|
| `jellyfin.py` | Media server: health, recent items, random items, user creation |
| `minecraft.py` | Server List Ping: status, player list, failover per server |
| `navidrome.py` | Music server: user creation, existence check |
| `nextcloud.py` | File sync: user creation via OCS API |
| `romm.py` | ROM manager: user creation |
| `registration.py` | Orchestrates multi-service registration, password generation, result aggregation |
| `password_utils.py` | Cryptographically secure password generation |
| `user_registry.py` | JSON persistence for Discord ID → username/email mappings |

### 4. Jellyfin Cogs (`bot/cogs/jellyfin/`)

- **announcements.py**: Scheduled content announcements, `/jf-status`, `/jf-announce`
- **health.py**: Interval-based health checks, state transition notifications
- **suggestions.py**: Scheduled random suggestions, `/jf-suggest`

### 5. Minecraft Cogs (`bot/cogs/minecraft/`)

- **health.py**: Per-server health checks, state transitions, `/mc-status`
- **players.py**: Player join detection via polling, join announcements

### 6. Registration Cog (`bot/cogs/registration/`)

- **handler.py**: Listens for DMs containing `register <username> <email>`, validates input, calls `RegistrationService`, sends embed with results and password. Also provides `/register` slash command.

### 7. Scheduler (`bot/services/scheduler.py`)

Factory `create_scheduler(config)` returns an `AsyncIOScheduler` with timezone and job defaults (coalesce=True, max_instances=1). Utility `parse_time("17:00")` returns `(17, 0)` for CronTrigger.

---

## Data Flow

### Startup Sequence

```
1. main.py: Parse CLI args
2. main.py: load_config() → Config object
3. main.py: Create MonolithBot(config, test_modes)
4. MonolithBot.setup_hook():
   ├── Create JellyfinService (if jellyfin.enabled)
   ├── Create MinecraftService (if minecraft.enabled)
   ├── Load cogs (conditional):
   │   ├── bot.cogs.jellyfin.announcements, health, suggestions (if jellyfin)
   │   ├── bot.cogs.minecraft.health, players (if minecraft)
   │   └── bot.cogs.registration.handler (if registration.enabled)
   └── Sync slash commands
5. MonolithBot.on_ready(): Log connection info, run test modes if enabled
6. Bot runs until shutdown signal
```

### Announcement Flow

```
1. Scheduler triggers at configured time (e.g., 17:00 PST)
2. _run_announcement() called
3. JellyfinService.get_all_recent_items() fetches new content (uses cached active URL)
4. For each content type with items:
   a. Send section header embed
   b. For each item (max per type):
      - Create embed with title, description, thumbnail, link
      - Send to announcement channel
5. Update _last_announcement timestamp
```

### Health Check Flow (Jellyfin and Minecraft)

```
1. Scheduler triggers every N minutes
2. _run_health_check() called
3. Service.check_health() tries URLs in order (health checks always start from primary)
4. Compare result to previous state
5. If state changed:
   - online→offline: Send "Server Offline" embed
   - offline→online: Send "Server Online" embed with downtime
6. Update state tracking variables
```

### Registration Flow

```
1. User DMs bot: "register myusername myemail@example.com" (or uses /register)
2. RegistrationCog.on_message() or suggest_command() receives request
3. Validate username and email format
4. Check UserRegistry: if already registered, optionally offer password reset
5. RegistrationService.register_user():
   a. Generate password (password_utils.generate_password)
   b. For each enabled service (Jellyfin, NextCloud, Navidrome, Organizr, Romm):
      - Check if user exists
      - If not, create user with generated password
      - Record result (success, skipped, failed)
   c. Return RegistrationResult with password and per-service status
6. UserRegistry.add_user() to persist mapping
7. Send embed with results and password (DM only, spoiler-tagged)
```

---

## Configuration System

See `config.json.example` and `.env.example` for full examples. The README documents all configuration options. Key principle: environment variables override JSON values.

---

## Registration System

The registration feature allows new Discord users to create accounts on multiple self-hosted services with a single command. It requires:

- **Message Content Intent**: Enabled in Discord Developer Portal for text-based DM registration
- **Admin credentials**: For each service (NextCloud, Navidrome, Organizr, Romm); Jellyfin uses its API key
- **User registry**: Persists Discord ID → username/email in a JSON file (path configurable)

**Adding a new registration service**:
1. Create a client and service in `bot/services/` (follow `navidrome.py` pattern)
2. Add config dataclass and loader in `bot/config.py`
3. Integrate into `bot/services/registration.py` `RegistrationService`
4. Add user creation and existence-check logic

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

### Running the Bot

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

5. Use granular test modes to trigger specific actions immediately:
   ```bash
   # Run all test modes (health check + announcement)
   python -m bot.main --test

   # Test only health check functionality
   python -m bot.main --test-health

   # Test only announcement functionality
   python -m bot.main --test-announcement

   # Combine with verbose for debugging
   python -m bot.main --test-announcement --verbose
   ```

**Note**: In test mode, announcement embeds include additional metadata showing when items were added to the library, helping verify that time filtering is working correctly.

---

## Testing

### Test Framework

MonolithBot uses **pytest** with the following extensions:

| Package | Purpose |
|---------|---------|
| `pytest` | Test framework |
| `pytest-asyncio` | Async test support |
| `pytest-cov` | Coverage reporting |
| `aioresponses` | Mock aiohttp responses |

### Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=bot --cov-report=term-missing

# Run specific test file
pytest tests/test_jellyfin.py

# Run specific test class or method
pytest tests/test_jellyfin.py::TestJellyfinClient::test_check_health_success
```

### Test Structure

```
tests/
├── conftest.py                 # Shared fixtures (configs, mocks, sample data)
├── test_config.py              # Config loading, validation, env var handling
├── test_jellyfin.py            # Jellyfin API client, HTTP mocking
├── test_announcements.py       # Announcements cog, embed creation
├── test_health.py              # Jellyfin health monitoring
├── test_suggestions.py         # Suggestions cog
├── test_minecraft_service.py   # Minecraft service, failover
├── test_minecraft_cogs.py      # Minecraft health and players cogs
├── test_main.py                # CLI args, TestModes, logging
├── test_scheduler.py           # Scheduler creation, parse_time
├── test_registration.py        # Registration orchestrator
├── test_registration_handler.py # Registration cog
├── test_navidrome.py           # Navidrome service
├── test_nextcloud.py           # NextCloud service
├── test_organizr.py            # Organizr service
├── test_romm.py                # Romm service
├── test_password_utils.py      # Password generation
└── test_user_registry.py       # User registry persistence
```

### Key Fixtures (`conftest.py`)

| Fixture | Description |
|---------|-------------|
| `config` | Complete mock Config object |
| `mock_bot` | Mock MonolithBot with config and channels |
| `mock_discord_channel` | Mock Discord TextChannel |
| `jellyfin_movie` | Sample JellyfinItem (Movie) |
| `jellyfin_episode` | Sample JellyfinItem (Episode) |
| `server_info` | Sample ServerInfo response |
| `minecraft_config` | Minecraft configuration with server list |

### Writing New Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

class TestMyFeature:
    @pytest.fixture
    def my_fixture(self, mock_bot):
        # Setup code using existing fixtures
        return MyClass(mock_bot)

    @pytest.mark.asyncio
    async def test_async_method(self, my_fixture):
        result = await my_fixture.do_something()
        assert result == expected

    def test_sync_method(self, my_fixture):
        result = my_fixture.calculate()
        assert result == 42
```

### Mocking HTTP Requests

Use `aioresponses` to mock Jellyfin API calls:

```python
from aioresponses import aioresponses
import re

@pytest.mark.asyncio
async def test_api_call(self, client):
    with aioresponses() as mocked:
        # Mock with exact URL
        mocked.get("http://localhost:8096/System/Info", payload={"ServerName": "Test"})

        # Mock with regex for URLs with query params
        mocked.get(re.compile(r"^http://localhost:8096/Items\?.*"), payload={"Items": []})

        result = await client.check_health()
        assert result.server_name == "Test"
```

### Continuous Integration

The `.github/workflows/ci.yml` workflow runs on every push and PR:

1. **Test Job**: Runs pytest on Python 3.10, 3.11, and 3.12
2. **Lint Job**: Runs Ruff for code quality checks

```yaml
# Tests run automatically on:
on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]
```

### Coverage Requirements

The project has a minimum coverage threshold of 60% configured in `pyproject.toml`. Current coverage is ~69%.

---

## Common Tasks

| Task | Location | Notes |
|------|----------|-------|
| Change announcement embed appearance | `jellyfin/announcements.py` → `_create_item_embed()` | Modify embed fields, colors |
| Add new Jellyfin content type | `config.py`, `jellyfin.py` → `_map_content_type()` | Map friendly name to Jellyfin type |
| Change Jellyfin health check behavior | `jellyfin/health.py` → `_run_health_check()` | Modify check logic or notifications |
| Change Minecraft health check behavior | `minecraft/health.py` | Same state-transition pattern |
| Add new Jellyfin API call | `jellyfin.py` | Add async method to client and service |
| Add new registration service | `bot/services/`, `config.py`, `registration.py` | Follow Navidrome/NextCloud pattern |
| Add new slash command | Any cog | Use `@app_commands.command` decorator |
| Add new configuration option | `config.py` | Add to dataclass and builder, update .env.example |
| Add tests for new feature | `tests/` | Create test file or add to existing; use conftest fixtures |
| Run tests | Terminal | `pytest` or `pytest -v --cov=bot` |
| Format code | Terminal | `ruff format .` and `ruff check .` |

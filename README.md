# MonolithBot

A Discord bot for monitoring your Jellyfin media server and Minecraft game servers, with multi-service user registration. MonolithBot keeps your Discord community updated on new media content, server status, and player activity.

## Features

### Jellyfin Media Server
- **📢 Content Announcements**: Automatically announce newly added movies, TV shows, and music at scheduled times
- **🎲 Random Suggestions**: Post random content suggestions from your library
- **🔔 Server Health Monitoring**: Get notified when Jellyfin goes down and when it comes back online
- **🔄 Multi-URL Failover**: Configure multiple Jellyfin URLs for automatic failover (e.g., internal/external, primary/backup)
- **🎨 Rich Embeds**: Beautiful Discord embeds with cover images and direct links to your content

### Minecraft Game Servers
- **🖥️ Multi-Server Support**: Monitor multiple Minecraft Java Edition servers independently
- **🔔 Health Monitoring**: Get notified when servers go offline or come back online
- **👥 Player Join Announcements**: Announce when players join your servers
- **🔄 Multi-URL Failover**: Configure backup addresses per server for automatic failover
- **📊 Status Details**: Version, player count, MOTD, and latency tracking

### Multi-Service User Registration
- **🔐 One-Click Registration**: New users can DM the bot to register on all your services at once
- **🌐 Supported Services**: Jellyfin, NextCloud, Navidrome, Organizr, and Romm
- **🔑 Secure Password Generation**: Cryptographically secure passwords generated and delivered via DM
- **📋 Per-Service Status**: See exactly which services were registered, skipped, or failed
- **🎯 Smart Handling**: Gracefully handles users who already exist on some services
- **🔄 Password Reset**: Reset passwords across all services with a single command

### General
- **⚙️ Flexible Configuration**: Configure via JSON file (local) or environment variables (Docker)
- **✅ Well Tested**: Comprehensive test suite with 500+ tests and CI/CD integration

## Quick Start

### Prerequisites

- Python 3.10+
- A Discord bot token ([Create one here](https://discord.com/developers/applications))
- A Jellyfin server with an API key (optional - [How to get one](https://jellyfin.org/docs/general/server/configuration/))
- Minecraft Java Edition servers (optional)

### Local Development

1. **Clone and install dependencies**
   ```bash
   git clone https://github.com/yourusername/MonolithBot.git
   cd MonolithBot
   pip install -r requirements.txt
   ```

2. **Create configuration**
   ```bash
   cp config.json.example config.json
   ```

3. **Edit `config.json`** with your settings (see [Configuration](#configuration) below)

4. **Run the bot**
   ```bash
   python -m bot.main
   ```

   With verbose logging:
   ```bash
   python -m bot.main --verbose
   ```

### Test Modes

Test modes trigger specific actions immediately on startup, useful for debugging and verification:

```bash
# Run all test modes
python -m bot.main --test

# Run all Jellyfin test modes
python -m bot.main --test-jellyfin

# Run all Minecraft test modes
python -m bot.main --test-minecraft

# Run specific tests
python -m bot.main --test-jf-health
python -m bot.main --test-mc-announce

# Combine flags
python -m bot.main --test-jellyfin --test-minecraft

# Combine with verbose for detailed output
python -m bot.main --test --verbose
```

| Flag | Description |
|------|-------------|
| `--test` / `-t` | Run all test modes (Jellyfin + Minecraft) |
| `--test-jellyfin` | Run all Jellyfin test modes |
| `--test-jf-health` | Run Jellyfin health check and send status message |
| `--test-jf-announcement` | Trigger Jellyfin content announcement immediately |
| `--test-jf-suggestion` | Trigger Jellyfin random suggestions immediately |
| `--test-minecraft` | Run all Minecraft test modes |
| `--test-mc-health` | Run Minecraft health check for all servers |
| `--test-mc-announce` | Run Minecraft player announcement test |

### Docker Deployment

The easiest way to deploy MonolithBot is with Docker. The image is automatically built and published to GitHub Container Registry.

1. **Create a directory and download the compose file**
   ```bash
   mkdir monolithbot && cd monolithbot
   curl -O https://raw.githubusercontent.com/StevenGann/MonolithBot/main/docker-compose.yml
   curl -O https://raw.githubusercontent.com/StevenGann/MonolithBot/main/.env.example
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env`** with your settings

4. **Run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

5. **Update to latest version**
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

## Configuration

### Discord Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `token` | Discord bot token | ✅ |
| `announcement_channel_id` | Default channel for content announcements | ✅ |
| `alert_channel_id` | Default channel for server alerts (defaults to announcement channel) | ❌ |

### Jellyfin Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `enabled` | Enable/disable Jellyfin integration (default: true) | ❌ |
| `urls` | List of Jellyfin server URLs to try in order | ✅ if enabled |
| `api_key` | Jellyfin API key | ✅ if enabled |
| `content_types` | Types of content to announce (default: Movie, Series, Audio) | ❌ |

#### Jellyfin Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `announcement_times` | `["17:00"]` | Times to announce new content (24h format) |
| `suggestion_times` | `["12:00", "20:00"]` | Times to post random suggestions |
| `timezone` | `America/Los_Angeles` | Timezone for scheduling |
| `health_check_interval_minutes` | `5` | How often to check server health |
| `lookback_hours` | `24` | How far back to look for new content |
| `max_items_per_type` | `10` | Maximum items to show per content type |

### Minecraft Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `enabled` | Enable/disable Minecraft integration (default: false) | ❌ |
| `announcement_channel_id` | Channel for player join announcements | ✅ if enabled |
| `alert_channel_id` | Channel for server status alerts | ✅ if enabled |
| `servers` | List of Minecraft server configurations | ✅ if enabled |

#### Minecraft Server Configuration

Each server in the `servers` list has:

| Setting | Description |
|---------|-------------|
| `name` | Display name for the server (e.g., "Survival", "Creative") |
| `urls` | List of server addresses to try in order (e.g., `["mc.example.com:25565"]`) |

#### Minecraft Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `timezone` | `America/Los_Angeles` | Timezone for scheduling |
| `health_check_interval_minutes` | `1` | How often to check server health |
| `player_check_interval_seconds` | `30` | How often to poll for player joins |

### Registration Settings

The registration feature allows new users to create accounts on multiple services by DMing the bot.

| Setting | Description | Required |
|---------|-------------|----------|
| `registration.enabled` | Enable/disable registration feature (default: false) | ❌ |

#### Service Configuration for Registration

Each service that users can register on has its own configuration:

**NextCloud:**
| Setting | Description | Required |
|---------|-------------|----------|
| `nextcloud.enabled` | Enable/disable NextCloud registration | ❌ |
| `nextcloud.urls` | List of NextCloud server URLs | ✅ if enabled |
| `nextcloud.admin_user` | Admin username for user creation | ✅ if enabled |
| `nextcloud.admin_password` | Admin password | ✅ if enabled |

**Navidrome:**
| Setting | Description | Required |
|---------|-------------|----------|
| `navidrome.enabled` | Enable/disable Navidrome registration | ❌ |
| `navidrome.urls` | List of Navidrome server URLs | ✅ if enabled |
| `navidrome.admin_user` | Admin username for user creation | ✅ if enabled |
| `navidrome.admin_password` | Admin password | ✅ if enabled |

**Organizr:**
| Setting | Description | Required |
|---------|-------------|----------|
| `organizr.enabled` | Enable/disable Organizr registration | ❌ |
| `organizr.urls` | List of Organizr server URLs | ✅ if enabled |
| `organizr.admin_user` | Admin username for user creation | ✅ if enabled |
| `organizr.admin_password` | Admin password | ✅ if enabled |

**Romm:**
| Setting | Description | Required |
|---------|-------------|----------|
| `romm.enabled` | Enable/disable Romm registration | ❌ |
| `romm.urls` | List of Romm server URLs | ✅ if enabled |
| `romm.admin_user` | Admin username for user creation | ✅ if enabled |
| `romm.admin_password` | Admin password | ✅ if enabled |

**Note:** Jellyfin uses the existing `jellyfin` configuration for registration.

### Additional Links Settings

You can add custom links to the `/help` command output:

| Setting | Description | Required |
|---------|-------------|----------|
| `additional_links` | Array of link objects to display in /help | ❌ |
| `additional_links[].name` | Display name for the link | ✅ |
| `additional_links[].url` | Full URL | ✅ |
| `additional_links[].description` | Optional description shown next to the link | ❌ |

### Service Descriptions

Each service (Jellyfin, Minecraft servers, NextCloud, Navidrome, Organizr, Romm) supports an optional `description` field that is shown in the `/help` command output.

### Logging Settings

Configure how MonolithBot logs events to files and console:

| Setting | Default | Description |
|---------|---------|-------------|
| `logging.log_directory` | `logs` | Directory for log files (create a volume mount in Docker) |
| `logging.log_level` | `INFO` | Minimum level to log (DEBUG, INFO, WARNING, ERROR) |
| `logging.log_to_console` | `true` | Output logs to stdout |
| `logging.log_to_file` | `true` | Write logs to timestamped files |

**Log Files:**
- New log file created on each bot startup
- Automatic rotation at midnight (timezone-aware)
- Filename format: `MonolithBot.YYYY-MM-DD.HH-MM-SS.log`

**Log Format:**
```
2024-01-15 17:00:00 | INFO     | CORE       | Bot started successfully
2024-01-15 17:00:05 | INFO     | JELLYFIN   | Health check: server online
2024-01-15 17:01:00 | INFO     | REGISTER   | Registration request from user 154789
```

**Tags:**
- `CORE` - Bot startup, shutdown, main events
- `JELLYFIN` - Jellyfin health, announcements, suggestions
- `MINECRAFT` - Minecraft health, player events
- `REGISTER` - User registration flow
- `NEXTCLOUD`, `NAVIDROME`, `ORGANIZR`, `ROMM` - Service-specific events
- `DISCORD` - Discord.py library events
- `SCHEDULER` - APScheduler job events

### Example Configuration

```json
{
  "discord": {
    "token": "YOUR_DISCORD_BOT_TOKEN",
    "announcement_channel_id": 123456789012345678,
    "alert_channel_id": 123456789012345678
  },
  "jellyfin": {
    "enabled": true,
    "urls": ["http://localhost:8096"],
    "api_key": "YOUR_JELLYFIN_API_KEY",
    "content_types": ["Movie", "Series", "Audio"],
    "schedule": {
      "announcement_times": ["17:00"],
      "suggestion_times": ["12:00", "20:00"],
      "timezone": "America/Los_Angeles",
      "health_check_interval_minutes": 5,
      "lookback_hours": 24
    }
  },
  "minecraft": {
    "enabled": true,
    "announcement_channel_id": 123456789012345678,
    "alert_channel_id": 123456789012345678,
    "servers": [
      {
        "name": "Survival",
        "urls": ["mc.example.com:25565", "backup.example.com:25565"]
      },
      {
        "name": "Creative",
        "urls": ["creative.example.com:25565"]
      }
    ],
    "schedule": {
      "health_check_interval_minutes": 1,
      "player_check_interval_seconds": 30
    }
  },
  "nextcloud": {
    "enabled": true,
    "urls": ["https://nextcloud.example.com"],
    "admin_user": "admin",
    "admin_password": "YOUR_ADMIN_PASSWORD"
  },
  "navidrome": {
    "enabled": true,
    "urls": ["https://navidrome.example.com"],
    "admin_user": "admin",
    "admin_password": "YOUR_ADMIN_PASSWORD"
  },
  "organizr": {
    "enabled": true,
    "urls": ["https://organizr.example.com"],
    "admin_user": "admin",
    "admin_password": "YOUR_ADMIN_PASSWORD",
    "description": "Services dashboard"
  },
  "romm": {
    "enabled": true,
    "urls": ["https://romm.example.com"],
    "admin_user": "admin",
    "admin_password": "YOUR_ADMIN_PASSWORD",
    "description": "ROM library manager"
  },
  "registration": {
    "enabled": true
  },
  "additional_links": [
    {
      "name": "Wiki",
      "url": "https://wiki.example.com",
      "description": "Documentation and guides"
    }
  ]
}
```

### Multi-URL Failover

Both Jellyfin and Minecraft support multiple URLs for automatic failover:

**Jellyfin:**
```json
{
  "jellyfin": {
    "urls": [
      "http://jellyfin-internal:8096",
      "https://jellyfin.example.com"
    ]
  }
}
```

**Minecraft:**
```json
{
  "minecraft": {
    "servers": [
      {
        "name": "Survival",
        "urls": ["mc.internal:25565", "mc.example.com:25565"]
      }
    ]
  }
}
```

**How it works:**
- During health checks, URLs are tried from top to bottom
- The first responding URL is cached for subsequent API calls
- Health checks always restart from the primary (first) URL
- If primary recovers, the bot automatically switches back to it

**Use cases:**
- Internal IP + external domain (prefer internal when available)
- Primary server + backup/replica server
- Different access methods for the same server

## Environment Variables

For Docker deployment, use these environment variables:

### Discord
| Variable | JSON Equivalent |
|----------|-----------------|
| `DISCORD_TOKEN` | `discord.token` |
| `DISCORD_ANNOUNCEMENT_CHANNEL_ID` | `discord.announcement_channel_id` |
| `DISCORD_ALERT_CHANNEL_ID` | `discord.alert_channel_id` |

### Jellyfin
| Variable | JSON Equivalent |
|----------|-----------------|
| `JELLYFIN_ENABLED` | `jellyfin.enabled` |
| `JELLYFIN_URL` | `jellyfin.urls` (single or comma-separated) |
| `JELLYFIN_API_KEY` | `jellyfin.api_key` |
| `JELLYFIN_CONTENT_TYPES` | `jellyfin.content_types` (comma-separated) |
| `JELLYFIN_SCHEDULE_ANNOUNCEMENT_TIMES` | `jellyfin.schedule.announcement_times` |
| `JELLYFIN_SCHEDULE_SUGGESTION_TIMES` | `jellyfin.schedule.suggestion_times` |
| `SCHEDULE_TIMEZONE` | `jellyfin.schedule.timezone` |
| `JELLYFIN_SCHEDULE_HEALTH_CHECK_INTERVAL` | `jellyfin.schedule.health_check_interval_minutes` |
| `JELLYFIN_SCHEDULE_LOOKBACK_HOURS` | `jellyfin.schedule.lookback_hours` |
| `JELLYFIN_SCHEDULE_MAX_ITEMS_PER_TYPE` | `jellyfin.schedule.max_items_per_type` |

### Minecraft
| Variable | JSON Equivalent |
|----------|-----------------|
| `MINECRAFT_ENABLED` | `minecraft.enabled` |
| `MINECRAFT_ANNOUNCEMENT_CHANNEL_ID` | `minecraft.announcement_channel_id` |
| `MINECRAFT_ALERT_CHANNEL_ID` | `minecraft.alert_channel_id` |
| `MINECRAFT_SCHEDULE_HEALTH_CHECK_INTERVAL` | `minecraft.schedule.health_check_interval_minutes` |
| `MINECRAFT_SCHEDULE_PLAYER_CHECK_INTERVAL` | `minecraft.schedule.player_check_interval_seconds` |

**Note**: Minecraft server definitions (name, URLs) must be configured in `config.json` and cannot be set via environment variables.

### Registration Services
| Variable | JSON Equivalent |
|----------|-----------------|
| `REGISTRATION_ENABLED` | `registration.enabled` |
| `NEXTCLOUD_ENABLED` | `nextcloud.enabled` |
| `NEXTCLOUD_URL` | `nextcloud.urls` (single or comma-separated) |
| `NEXTCLOUD_ADMIN_USER` | `nextcloud.admin_user` |
| `NEXTCLOUD_ADMIN_PASSWORD` | `nextcloud.admin_password` |
| `NAVIDROME_ENABLED` | `navidrome.enabled` |
| `NAVIDROME_URL` | `navidrome.urls` (single or comma-separated) |
| `NAVIDROME_ADMIN_USER` | `navidrome.admin_user` |
| `NAVIDROME_ADMIN_PASSWORD` | `navidrome.admin_password` |
| `ROMM_ENABLED` | `romm.enabled` |
| `ROMM_URL` | `romm.urls` (single or comma-separated) |
| `ROMM_ADMIN_USER` | `romm.admin_user` |
| `ROMM_ADMIN_PASSWORD` | `romm.admin_password` |
| `ORGANIZR_ENABLED` | `organizr.enabled` |
| `ORGANIZR_URL` | `organizr.urls` (single or comma-separated) |
| `ORGANIZR_ADMIN_USER` | `organizr.admin_user` |
| `ORGANIZR_ADMIN_PASSWORD` | `organizr.admin_password` |

## Bot Commands

### Jellyfin Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/jf-status` | Check Jellyfin server status | Everyone |
| `/jf-announce` | Manually trigger a content announcement | Administrator |
| `/jf-suggest` | Get random content suggestions | Everyone |

### Minecraft Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/mc-status` | Check all Minecraft server status | Everyone |
| `/mc-players` | Show who's playing on each server | Everyone |

### General Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/help` | Show available services and links | Everyone |

### Registration Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/register` | Register on all enabled services (DM only) | Everyone |
| `/reset-password` | Reset password on all services (DM only) | Everyone |
| DM: `register <username> <email>` | Alternative text-based registration | Everyone |
| DM: `reset-password` | Alternative text-based password reset | Everyone |

**Registration Usage:**

1. **Via Slash Command** (recommended):
   - DM the bot and use `/register`
   - Enter your desired username and email address
   - The bot will register you on all enabled services

2. **Via Text Message**:
   - DM the bot with: `register myusername myemail@example.com`
   - The bot will process your registration request

**What you'll receive:**
- A summary showing which services you were registered on
- Services where you already had an account (skipped)
- Any services that failed (with error details)
- Your generated password (shown as a spoiler for security)

**Password Reset:**

If you've forgotten your password, you can reset it across all services:
1. DM the bot with `/reset-password` or type `reset-password`
2. A new password will be generated and set on all services where you have an account
3. You'll receive the new password via DM

## Development

### Discord Developer Portal Setup

For basic bot functionality, no special setup is needed beyond creating the bot and inviting it to your server.

**For Registration Feature (Required):**

The registration feature requires the **Message Content Intent** to read DM messages. This is a privileged intent that must be enabled manually:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your bot application
3. Navigate to **Bot** in the left sidebar
4. Scroll down to **Privileged Gateway Intents**
5. Enable **Message Content Intent**
6. Click **Save Changes**

![Message Content Intent Setting](https://i.imgur.com/example.png)

**Why is this required?**
- Discord requires explicit opt-in for bots to read message content
- The registration feature parses DM messages like `register username email@example.com`
- The slash command `/register` works without this intent, but text-based registration requires it

**Note:** Bots in 100+ servers require verification to use privileged intents. For smaller servers, you can enable it immediately.

### Running Tests

MonolithBot includes a comprehensive test suite using pytest:

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=bot --cov-report=term-missing

# Run specific test file
pytest tests/test_minecraft_service.py
```

### Test Structure

```
tests/
├── conftest.py                 # Shared fixtures (configs, mocks)
├── test_config.py              # Configuration loading and validation
├── test_jellyfin.py            # Jellyfin API client
├── test_announcements.py       # Jellyfin announcements cog
├── test_health.py              # Jellyfin health monitoring
├── test_suggestions.py         # Jellyfin suggestions cog
├── test_minecraft_service.py   # Minecraft service
├── test_minecraft_cogs.py      # Minecraft health and players cogs
├── test_main.py                # CLI, TestModes, logging
├── test_scheduler.py           # Scheduler utilities
├── test_registration.py        # Registration orchestrator
├── test_registration_handler.py # Registration cog
├── test_navidrome.py           # Navidrome service
├── test_nextcloud.py           # NextCloud service
├── test_romm.py                # Romm service
├── test_password_utils.py      # Password generation
└── test_user_registry.py       # User registry
```

### For Developers

- **[ARCHITECTURE.md](ARCHITECTURE.md)** – Architecture, data flow, and extension guide for maintainers
- **[CONTRIBUTING.md](CONTRIBUTING.md)** – Contribution guidelines and development workflow

### Continuous Integration

Tests run automatically on every push and pull request via GitHub Actions. The CI workflow:

- Runs tests on Python 3.10, 3.11, and 3.12
- Generates coverage reports
- Runs Ruff linter for code quality checks

## Getting Your Discord Channel ID

1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click on the channel
3. Click "Copy Channel ID"

## Getting Your Jellyfin API Key

1. Log into Jellyfin as an admin
2. Go to Dashboard → API Keys
3. Click "+" to create a new key
4. Name it "MonolithBot" and copy the key

## Troubleshooting

### Bot doesn't respond to commands
- Ensure the bot has proper permissions in the channel
- Wait a minute for slash commands to sync after first startup

### Can't connect to Jellyfin
- Verify the Jellyfin URL is correct and accessible from where the bot runs
- If using Docker, ensure both containers are on the same network
- Check the API key has proper permissions

### Jellyfin announcements not appearing
- Check the channel ID is correct
- Verify there's actually new content in the lookback period
- Run `/jf-status` to check connectivity
- Use `--test-jf-announcement` flag to trigger an immediate announcement for debugging

### Minecraft server shows offline
- Verify the server address and port are correct (default port is 25565)
- Ensure the bot can reach the server (network, firewall)
- Check that the server is configured for Server List Ping (SLP)
- Use `--test-minecraft` flag to check connectivity

### Player joins not being announced
- Some servers hide player lists - this is a server-side setting
- Verify the polling interval isn't too long (default: 30 seconds)
- Check that `announcement_channel_id` is configured for Minecraft

### Registration not working

**"Registration is not available" message:**
- Ensure `registration.enabled` is set to `true` in config
- At least one service (Jellyfin, NextCloud, Navidrome, or Romm) must be enabled
- Restart the bot after changing configuration

**Bot doesn't respond to DM messages:**
- Enable **Message Content Intent** in Discord Developer Portal (see [setup instructions](#discord-developer-portal-setup))
- The `/register` slash command should still work without this intent

**"Failed to register on [service]" errors:**
- Verify the service URL is accessible from where the bot runs
- Check admin credentials have permission to create users
- For NextCloud: Ensure the admin user has user provisioning rights
- For Navidrome: Admin user must have admin role
- For Romm: Admin credentials must be valid OAuth2 credentials
- For Organizr: Admin user must have user management permissions

**User already exists:**
- This is expected behavior - the bot skips services where the username already exists
- The response will show which services were skipped vs newly registered

### Updating the Bot

To update to the latest version on your server:

```bash
docker-compose pull
docker-compose up -d
```

### Version Tags

The workflow automatically creates these image tags:
- `latest` - Always points to the most recent `main`/`master` build
- `v1.0.0`, `v1.0`, etc. - Created when you push version tags (e.g., `git tag v1.0.0 && git push --tags`)

To pin to a specific version instead of `latest`, edit `docker-compose.yml`:
```yaml
image: ghcr.io/stevengann/monolithbot:v1.0.0
```

## License

MIT License - feel free to modify and distribute.

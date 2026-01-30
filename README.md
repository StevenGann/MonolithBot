# MonolithBot

A Discord bot for monitoring your Jellyfin media server and Minecraft game servers. MonolithBot keeps your Discord community updated on new media content, server status, and player activity.

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

### General
- **⚙️ Flexible Configuration**: Configure via JSON file (local) or environment variables (Docker)
- **✅ Well Tested**: Comprehensive test suite with 300+ tests and CI/CD integration

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
  }
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

## Development

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
├── conftest.py                 # Shared fixtures
├── test_config.py              # Configuration tests
├── test_jellyfin.py            # Jellyfin API client tests
├── test_minecraft_service.py   # Minecraft service tests
├── test_minecraft_cogs.py      # Minecraft cog tests
├── test_scheduler.py           # Scheduler utility tests
├── test_announcements.py       # Announcements cog tests
└── test_health.py              # Health monitoring tests
```

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

## GitHub Container Registry Setup (Maintainer)

After the first push to `main`/`master`, the GitHub Actions workflow will build and publish the Docker image. However, GitHub packages are private by default. To make the image publicly pullable:

1. Go to https://github.com/StevenGann/MonolithBot/packages
2. Click on the `monolithbot` package
3. Click **Package settings** (right sidebar)
4. Scroll to **Danger Zone** → **Change package visibility**
5. Select **Public** and confirm

This only needs to be done once. After that, anyone can pull the image without authentication.

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

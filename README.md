# MonolithBot

A Discord bot for monitoring your Jellyfin media server. MonolithBot keeps your Discord community updated on new content and server status.

## Features

- **📢 Content Announcements**: Automatically announce newly added movies, TV shows, and music at scheduled times
- **🔔 Server Health Monitoring**: Get notified when Jellyfin goes down and when it comes back online
- **🔄 Multi-URL Failover**: Configure multiple Jellyfin URLs for automatic failover (e.g., internal/external, primary/backup)
- **🎨 Rich Embeds**: Beautiful Discord embeds with cover images and direct links to your content
- **⚙️ Flexible Configuration**: Configure via JSON file (local) or environment variables (Docker)
- **✅ Well Tested**: Comprehensive test suite with 200+ tests and CI/CD integration

## Quick Start

### Prerequisites

- Python 3.10+
- A Discord bot token ([Create one here](https://discord.com/developers/applications))
- A Jellyfin server with an API key ([How to get one](https://jellyfin.org/docs/general/server/configuration/))

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

3. **Edit `config.json`** with your settings:
   ```json
   {
     "discord": {
       "token": "YOUR_DISCORD_BOT_TOKEN",
       "announcement_channel_id": 123456789012345678,
       "alert_channel_id": 123456789012345678
     },
     "jellyfin": {
       "urls": ["http://localhost:8096"],
       "api_key": "YOUR_JELLYFIN_API_KEY"
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
# Run all test modes (health check + announcement)
python -m bot.main --test

# Run only health check test (sends status message immediately)
python -m bot.main --test-health

# Run only announcement test (triggers announcement immediately)
python -m bot.main --test-announcement

# Combine with verbose for detailed output
python -m bot.main --test --verbose
```

| Flag | Short | Description |
|------|-------|-------------|
| `--test` | `-t` | Run all test modes (equivalent to all individual flags) |
| `--test-health` | | Run health check and send status message |
| `--test-announcement` | | Trigger content announcement immediately |

In test mode, announcements include extra metadata showing when items were added to the library, helping verify time filtering is working correctly.

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

### Building Locally with Docker

If you want to build from source instead of using the pre-built image:

```bash
git clone https://github.com/StevenGann/MonolithBot.git
cd MonolithBot
cp .env.example .env
# Edit .env with your settings
docker-compose -f docker-compose.local.yml up -d --build
```

## Configuration

### Discord Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `token` | Discord bot token | ✅ |
| `announcement_channel_id` | Channel for content announcements | ✅ |
| `alert_channel_id` | Channel for server alerts (defaults to announcement channel) | ❌ |

### Jellyfin Settings

| Setting | Description | Required |
|---------|-------------|----------|
| `urls` | List of Jellyfin server URLs to try in order (e.g., `["http://primary:8096", "http://backup:8096"]`) | ✅ |
| `url` | Single Jellyfin server URL (backward-compatible, use `urls` for new configs) | ❌ |
| `api_key` | Jellyfin API key | ✅ |

#### Multi-URL Failover

MonolithBot supports multiple Jellyfin URLs for automatic failover. Configure your URLs in priority order:

```json
{
  "jellyfin": {
    "urls": [
      "http://jellyfin-internal:8096",
      "https://jellyfin.example.com"
    ],
    "api_key": "YOUR_API_KEY"
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

### Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `announcement_times` | `["17:00"]` | Times to announce new content (24h format) |
| `timezone` | `America/Los_Angeles` | Timezone for scheduling |
| `health_check_interval_minutes` | `5` | How often to check server health |
| `lookback_hours` | `24` | How far back to look for new content |
| `max_items_per_type` | `10` | Maximum items to show per content type |

### Content Types

Supported types: `Movie`, `Series`, `Audio`

## Environment Variables

For Docker deployment, use these environment variables:

| Variable | JSON Equivalent |
|----------|-----------------|
| `DISCORD_TOKEN` | `discord.token` |
| `DISCORD_ANNOUNCEMENT_CHANNEL_ID` | `discord.announcement_channel_id` |
| `DISCORD_ALERT_CHANNEL_ID` | `discord.alert_channel_id` |
| `JELLYFIN_URL` | `jellyfin.urls` (single URL or comma-separated list) |
| `JELLYFIN_API_KEY` | `jellyfin.api_key` |
| `SCHEDULE_ANNOUNCEMENT_TIMES` | `schedule.announcement_times` (comma-separated) |
| `SCHEDULE_TIMEZONE` | `schedule.timezone` |
| `SCHEDULE_HEALTH_CHECK_INTERVAL` | `schedule.health_check_interval_minutes` |
| `SCHEDULE_LOOKBACK_HOURS` | `schedule.lookback_hours` |
| `SCHEDULE_MAX_ITEMS_PER_TYPE` | `schedule.max_items_per_type` |
| `CONTENT_TYPES` | `content_types` (comma-separated) |

**Multi-URL Example:**
```bash
JELLYFIN_URL="http://internal:8096,https://external.example.com"
```

**Note**: Environment variables take precedence over JSON config values.

## Bot Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/status` | Check bot and Jellyfin server status | Everyone |
| `/announce` | Manually trigger a content announcement | Administrator |

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
pytest tests/test_jellyfin.py
```

### Test Structure

```
tests/
├── conftest.py           # Shared fixtures
├── test_config.py        # Configuration tests
├── test_jellyfin.py      # Jellyfin API client tests
├── test_scheduler.py     # Scheduler utility tests
├── test_announcements.py # Announcements cog tests
└── test_health.py        # Health monitoring tests
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

### Announcements not appearing
- Check the channel ID is correct
- Verify there's actually new content in the lookback period
- Run `/status` to check connectivity
- Use `--test-announcement` flag to trigger an immediate announcement for debugging

### Old content appearing in announcements
- The bot performs client-side filtering to ensure only content within the `lookback_hours` window is announced
- Check that your Jellyfin server's timezone is configured correctly
- Verify the `DateCreated` field is being set properly in Jellyfin

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

# MonolithBot

A Discord bot for monitoring your Jellyfin media server. MonolithBot keeps your Discord community updated on new content and server status.

## Features

- **📢 Content Announcements**: Automatically announce newly added movies, TV shows, and music at scheduled times
- **🔔 Server Health Monitoring**: Get notified when Jellyfin goes down and when it comes back online
- **🎨 Rich Embeds**: Beautiful Discord embeds with cover images and direct links to your content
- **⚙️ Flexible Configuration**: Configure via JSON file (local) or environment variables (Docker)

## Quick Start

### Prerequisites

- Python 3.11+
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
       "url": "http://localhost:8096",
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
| `url` | Jellyfin server URL (e.g., `http://jellyfin:8096`) | ✅ |
| `api_key` | Jellyfin API key | ✅ |

### Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `announcement_times` | `["17:00"]` | Times to announce new content (24h format) |
| `timezone` | `America/Los_Angeles` | Timezone for scheduling |
| `health_check_interval_minutes` | `5` | How often to check server health |
| `lookback_hours` | `24` | How far back to look for new content |

### Content Types

Supported types: `Movie`, `Series`, `Audio`

## Environment Variables

For Docker deployment, use these environment variables:

| Variable | JSON Equivalent |
|----------|-----------------|
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

**Note**: Environment variables take precedence over JSON config values.

## Bot Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/status` | Check bot and Jellyfin server status | Everyone |
| `/announce` | Manually trigger a content announcement | Administrator |

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

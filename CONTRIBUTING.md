# Contributing to MonolithBot

This document provides guidelines for developers who wish to contribute to MonolithBot or take over maintenance. It complements [ARCHITECTURE.md](ARCHITECTURE.md), which describes the codebase structure.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- A Discord bot token (for manual testing)
- Optional: Jellyfin, Minecraft, NextCloud, Navidrome, or Romm instances for integration testing

### Development Setup

```bash
# Clone the repository
git clone https://github.com/StevenGann/MonolithBot.git
cd MonolithBot

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Copy and edit configuration
cp config.json.example config.json
# Edit config.json with your test credentials
```

### Running the Bot Locally

```bash
python -m bot.main --verbose
```

Use `--test-jf-health` or similar flags to trigger specific features immediately without waiting for schedules.

## Development Workflow

### Code Style

- **Formatting**: Use [Ruff](https://docs.astral.sh/ruff/) for formatting and linting.
  ```bash
  ruff format .
  ruff check .
  ```
- **Type hints**: Use type annotations for function arguments and return values.
- **Docstrings**: Follow Google-style docstrings for modules, classes, and public functions. See existing modules (e.g., `bot/services/jellyfin.py`) for examples.

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=bot --cov-report=term-missing

# Run a specific test file
pytest tests/test_config.py
```

The project maintains a minimum 60% test coverage. Ensure new code is covered by tests.

### Pre-Commit Checklist

Before submitting changes:

1. Run tests: `pytest`
2. Run Ruff: `ruff format . && ruff check .`
3. Verify coverage: `pytest --cov=bot --cov-report=term-missing`

## Adding New Features

### Adding a New Cog

1. Create `bot/cogs/<category>/<cog_name>.py`
2. Implement the cog with `cog_load()` and `cog_unload()` for lifecycle
3. Register in `bot/main.py` in the appropriate `cogs_to_load` section (conditional on config)
4. Add tests in `tests/test_<cog_name>.py`
5. Update `ARCHITECTURE.md` directory structure

See [ARCHITECTURE.md - Extending the Bot](ARCHITECTURE.md#extending-the-bot) for code templates.

### Adding a New Service

1. Create `bot/services/<service>.py` with a Client (single URL) and Service (multi-URL failover) class
2. Follow the pattern in `bot/services/navidrome.py`
3. Add config dataclass and loader in `bot/config.py`
4. Add environment variable support in config builders
5. Update `config.json.example` and `.env.example`
6. Add tests in `tests/test_<service>.py`

### Adding a New Configuration Option

1. Add field to the appropriate dataclass in `bot/config.py`
2. Add to the builder function with env var override
3. Update `config.json.example`
4. Add to `.env.example` if applicable
5. Document in README.md Configuration section

## Documentation Standards

- **Module docstrings**: Describe the module's purpose, key features, and include a brief example. Reference related modules with "See Also."
- **Class docstrings**: Describe the class role and list main attributes.
- **Function docstrings**: Use Args, Returns, Raises sections. Keep examples concise.
- **README.md**: User-facing documentation (setup, configuration, commands).
- **ARCHITECTURE.md**: Developer-facing documentation (structure, flow, design decisions).
- **CONTRIBUTING.md**: Contribution workflow and standards (this file).

## Pull Request Process

1. Create a branch for your changes
2. Make changes with clear commits
3. Ensure all tests pass and Ruff passes
4. Update documentation as needed
5. Open a pull request with a description of the change
6. Address review feedback

## Release Process

1. Update version in `bot/__init__.py` and `pyproject.toml`
2. Update CHANGELOG if maintained
3. Create and push a version tag: `git tag v1.0.0 && git push --tags`
4. GitHub Actions will build and publish the Docker image

## Handoff Notes for New Maintainers

- **Secrets**: Never commit tokens or passwords. Use `config.json` (gitignored) or environment variables.
- **CI/CD**: `.github/workflows/ci.yml` runs tests and lint on push/PR. `docker-publish.yml` builds the image on main and on version tags.
- **Docker**: The image is published to `ghcr.io/stevengann/monolithbot`. See README for deployment instructions.
- **Support**: Check existing issues and the troubleshooting section in README for common problems.

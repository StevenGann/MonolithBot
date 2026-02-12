"""
Administrative web UI for MonolithBot.

Provides a login-protected dashboard (users list, send help, password reset,
register on behalf, manage admins) served via aiohttp in the same process as the bot.
"""

from bot.admin_ui.app import create_app

__all__ = ["create_app"]

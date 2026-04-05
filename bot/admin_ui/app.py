"""
aiohttp application for the admin UI.

Serves login, dashboard with tabs (Users, Send help, Password reset,
Register on behalf, Manage admins), and action handlers.

Route table:
    GET  /                              → redirect to /admin/
    GET  /admin/                        → login page (or redirect to dashboard)
    POST /admin/login                   → authenticate and set session cookie
    GET  /admin/logout                  → invalidate session and redirect to login
    GET  /admin/dashboard               → main dashboard (login required)
    POST /admin/action/send-help        → DM the /help embed to a Discord user
    POST /admin/action/send-message     → send a custom DM to one or all users
    POST /admin/action/password-reset   → reset a user's password and DM them
    POST /admin/action/register         → register a user on behalf of an admin
    POST /admin/action/add-admin        → add a pending admin username

Authentication:
    All dashboard routes are protected by the @_login_required decorator, which
    checks the "admin_session" cookie via auth.get_session(). The session token
    is stored in process memory (see bot.admin_ui.auth for lifetime notes).
    Session cookies are set with HttpOnly=True and SameSite=Strict.

Security notes:
    - Bind address defaults to 127.0.0.1. Do NOT expose to the network without
      a TLS-terminating reverse proxy.
    - Exception details from upstream services are logged server-side and a
      generic message is returned to the browser to prevent information leakage.

App keys (set via create_app):
    APP_KEY_BOT    – the running MonolithBot instance (may be None in tests)
    APP_KEY_CONFIG – the bot Config object (may be None in tests)
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING, Any, Optional

import discord
from aiohttp import web

from bot.admin_ui import auth

if TYPE_CHECKING:
    from bot.main import MonolithBot

logger = logging.getLogger("monolithbot.admin_ui")

# App keys for shared state
APP_KEY_BOT = "bot"
APP_KEY_CONFIG = "config"


def _get_bot(request: web.Request) -> Optional["MonolithBot"]:
    """Retrieve the MonolithBot instance stored in the aiohttp app registry.

    Args:
        request: The current aiohttp request.

    Returns:
        The MonolithBot instance, or None if not set (e.g., in tests).
    """
    return request.app.get(APP_KEY_BOT)


def _get_config(request: web.Request) -> Any:
    """Retrieve the bot Config object stored in the aiohttp app registry.

    Args:
        request: The current aiohttp request.

    Returns:
        The Config instance, or None if not set (e.g., in tests).
    """
    return request.app.get(APP_KEY_CONFIG)


def _get_login_path(request: web.Request) -> str:
    """Return the configured admin-login.json path, with a safe default.

    Args:
        request: The current aiohttp request.

    Returns:
        Filesystem path string for the admin credentials file.
    """
    cfg = _get_config(request)
    return (cfg and cfg.admin_ui.admin_login_file) or "data/admin-login.json"


def _session_username(request: web.Request) -> Optional[str]:
    """Extract and validate the session cookie, returning the admin username.

    Args:
        request: The current aiohttp request.

    Returns:
        The authenticated admin username, or None if the session is missing
        or expired.
    """
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    return auth.get_session(token)


def _login_required(handler):
    """Decorator that enforces authentication on a route handler.

    Redirects unauthenticated GET requests to the login page and returns
    401 for unauthenticated non-GET requests. Sets ``request["admin_username"]``
    for use by the wrapped handler.

    Args:
        handler: The async aiohttp route handler to protect.

    Returns:
        A wrapped handler that checks the session before delegating.
    """
    async def wrapper(request: web.Request) -> web.Response:
        username = _session_username(request)
        if not username:
            if request.method == "GET":
                return web.Response(status=302, headers={"Location": "/admin/"})
            return web.Response(status=401, text="Not logged in")
        request["admin_username"] = username
        return await handler(request)

    return wrapper


# -----------------------------------------------------------------------------
# HTML fragments and pages
# -----------------------------------------------------------------------------


def _base_html(title: str, body: str, extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.75rem; background: #1a1a2e; color: #eaeaea; min-height: 100vh; }}
a {{ color: #7eb8da; }}
input, button, select {{ padding: 0.5rem 0.75rem; margin: 0.25rem 0; border-radius: 4px; border: 1px solid #444; background: #2d2d44; color: #eaeaea; }}
button, .btn {{ cursor: pointer; background: #4a6fa5; color: #fff; border: none; }}
button:hover, .btn:hover {{ background: #5a7fb5; }}
.tabs {{ display: flex; flex-wrap: wrap; gap: 0.25rem; margin-bottom: 1rem; border-bottom: 1px solid #444; }}
.tabs a {{ padding: 0.5rem 1rem; text-decoration: none; color: #aaa; border-radius: 4px 4px 0 0; }}
.tabs a:hover {{ color: #eaeaea; background: #2d2d44; }}
.tabs a.active {{ color: #7eb8da; background: #2d2d44; }}
.panel {{ display: none; padding: 1rem 0; }}
.panel.active {{ display: block; }}
.form-group {{ margin: 0.75rem 0; }}
.form-group label {{ display: block; margin-bottom: 0.25rem; color: #aaa; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #333; }}
th {{ color: #888; }}
.msg {{ padding: 0.75rem; border-radius: 4px; margin: 0.75rem 0; }}
.msg.error {{ background: #5a2a2a; color: #f88; }}
.msg.success {{ background: #2a4a2a; color: #8f8; }}
.header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }}
</style>
{extra_head}
</head>
<body>
{body}
</body>
</html>"""


def _login_page(error: str = "") -> str:
    err = f'<div class="msg error">{html.escape(error)}</div>' if error else ""
    return _base_html(
        "Admin Login",
        f"""
<div style="max-width: 400px; margin: 2rem auto;">
<h1>MonolithBot Admin</h1>
{err}
<form method="post" action="/admin/login">
<div class="form-group">
<label for="username">Username</label>
<input type="text" id="username" name="username" required autocomplete="username">
</div>
<div class="form-group">
<label for="password">Password</label>
<input type="password" id="password" name="password" required autocomplete="current-password">
</div>
<button type="submit">Log in</button>
</form>
</div>
""",
    )


def _dashboard_page(
    request: web.Request, active_tab: str = "users", message: str = "", error: str = ""
) -> str:
    username = request["admin_username"]
    is_initial = auth.is_initial_admin(_get_login_path(request), username)
    msg_html = (
        f'<div class="msg success">{html.escape(message)}</div>' if message else ""
    )
    err_html = f'<div class="msg error">{html.escape(error)}</div>' if error else ""

    tabs = [
        ("users", "Users"),
        ("sendhelp", "Send help"),
        ("sendmessage", "Send message"),
        ("reset", "Password reset"),
        ("register", "Register user"),
    ]
    if is_initial:
        tabs.append(("admins", "Manage admins"))

    tab_links = "".join(
        f'<a href="#" class="tab-link {"active" if t[0] == active_tab else ""}" data-tab="{t[0]}">{html.escape(t[1])}</a>'
        for t in tabs
    )

    return _base_html(
        "Admin Dashboard",
        f"""
<div class="header">
<h1>MonolithBot Admin</h1>
<span>Logged in as <strong>{html.escape(username)}</strong> | <a href="/admin/logout">Log out</a></span>
</div>
{msg_html}
{err_html}
<nav class="tabs" role="tablist">{tab_links}</nav>

<div id="panel-users" class="panel {"active" if active_tab == "users" else ""}" data-tab="users">
<h2>Registered users</h2>
<div id="users-content">Loading...</div>
</div>

<div id="panel-sendhelp" class="panel {"active" if active_tab == "sendhelp" else ""}" data-tab="sendhelp">
<h2>Send help message</h2>
<p>Send the same help message as /help to a user via DM. Use their Discord user ID (snowflake).</p>
<form method="post" action="/admin/action/send-help">
<div class="form-group">
<label for="sendhelp_id">Discord user ID</label>
<input type="text" id="sendhelp_id" name="discord_id" required placeholder="123456789012345678">
</div>
<button type="submit">Send help DM</button>
</form>
</div>

<div id="panel-sendmessage" class="panel {"active" if active_tab == "sendmessage" else ""}" data-tab="sendmessage">
<h2>Send message</h2>
<p>Send a custom message to a user via DM, or to all registered users. Optionally send to all active Jellyfin sessions when sending to all.</p>
<form method="post" action="/admin/action/send-message">
<div class="form-group">
<label>Target</label>
<label><input type="radio" name="target" value="one" checked> One user (by Discord ID)</label>
<label><input type="radio" name="target" value="all"> All registered users</label>
</div>
<div class="form-group" id="sendmsg-discord-id-group">
<label for="sendmsg_discord_id">Discord user ID</label>
<input type="text" id="sendmsg_discord_id" name="discord_id" placeholder="123456789012345678">
</div>
<div class="form-group">
<label for="sendmsg_message">Message</label>
<textarea id="sendmsg_message" name="message" required rows="4" placeholder="e.g. We will be doing maintenance tonight..."></textarea>
</div>
<div class="form-group">
<label for="sendmsg_header">Header (optional)</label>
<input type="text" id="sendmsg_header" name="header" placeholder="Message from Monolith">
</div>
<div class="form-group" id="sendmsg-jellyfin-group" style="display:none">
<label><input type="checkbox" name="send_to_jellyfin" value="1"> Also send to all active Jellyfin sessions</label>
</div>
<button type="submit">Send</button>
</form>
</div>

<div id="panel-reset" class="panel {"active" if active_tab == "reset" else ""}" data-tab="reset">
<h2>Trigger password reset</h2>
<p>Reset password for a registered user. They will receive the new password via DM.</p>
<form method="post" action="/admin/action/password-reset">
<div class="form-group">
<label for="reset_username">Monolith username</label>
<input type="text" id="reset_username" name="username" required placeholder="johndoe">
</div>
<button type="submit">Reset password and DM user</button>
</form>
</div>

<div id="panel-register" class="panel {"active" if active_tab == "register" else ""}" data-tab="register">
<h2>Register a user on their behalf</h2>
<p>Provide Discord ID, Monolith username, and email. The bot will register them and can DM the result.</p>
<form method="post" action="/admin/action/register">
<div class="form-group">
<label for="reg_discord_id">Discord user ID</label>
<input type="text" id="reg_discord_id" name="discord_id" required placeholder="123456789012345678">
</div>
<div class="form-group">
<label for="reg_username">Monolith username</label>
<input type="text" id="reg_username" name="username" required placeholder="johndoe">
</div>
<div class="form-group">
<label for="reg_email">Email</label>
<input type="email" id="reg_email" name="email" required placeholder="user@example.com">
</div>
<button type="submit">Register and DM user</button>
</form>
</div>

<div id="panel-admins" class="panel {"active" if active_tab == "admins" else ""}" data-tab="admins">
<h2>Add admin</h2>
<p>Add a username. When they log in for the first time, the password they enter will become their password.</p>
<form method="post" action="/admin/action/add-admin">
<div class="form-group">
<label for="new_admin_username">New admin username</label>
<input type="text" id="new_admin_username" name="username" required>
</div>
<button type="submit">Add pending admin</button>
</form>
</div>

<script>
document.querySelectorAll('.tab-link').forEach(function(a) {{
  a.addEventListener('click', function(e) {{
    e.preventDefault();
    var t = a.getAttribute('data-tab');
    document.querySelectorAll('.tab-link').forEach(function(x) {{ x.classList.remove('active'); }});
    document.querySelectorAll('.panel').forEach(function(p) {{ p.classList.remove('active'); }});
    a.classList.add('active');
    var panel = document.getElementById('panel-' + t);
    if (panel) panel.classList.add('active');
  }});
}});
(function() {{
  var form = document.querySelector('form[action="/admin/action/send-message"]');
  if (!form) return;
  var targetRadios = form.querySelectorAll('input[name="target"]');
  var discordIdGroup = document.getElementById('sendmsg-discord-id-group');
  var jellyfinGroup = document.getElementById('sendmsg-jellyfin-group');
  var discordIdInput = document.getElementById('sendmsg_discord_id');
  function updateSendMessageTarget() {{
    var target = form.querySelector('input[name="target"]:checked');
    var isAll = target && target.value === 'all';
    if (discordIdGroup) discordIdGroup.style.display = isAll ? 'none' : 'block';
    if (discordIdInput) discordIdInput.required = !isAll;
    if (jellyfinGroup) jellyfinGroup.style.display = isAll ? 'block' : 'none';
  }}
  targetRadios.forEach(function(r) {{ r.addEventListener('change', updateSendMessageTarget); }});
  updateSendMessageTarget();
}})();
</script>
""",
    )


async def _render_users_table(request: web.Request) -> str:
    bot = _get_bot(request)
    if not bot:
        return "<p>Bot not available.</p>"
    cog = bot.get_cog("Registration")
    if not cog or not getattr(cog, "user_registry", None):
        return "<p>Registration not loaded or no user registry.</p>"
    registry = cog.user_registry
    # registry.load() is idempotent and guarded by self._loaded, but the
    # registry is already loaded by the cog on startup — no reload needed.
    users = registry.get_all_users()
    if not users:
        return "<p>No registered users.</p>"
    rows = []
    for u in users:
        services = ", ".join(u.services) if u.services else "—"
        rows.append(
            f"<tr><td>{u.discord_id}</td><td>{html.escape(u.discord_name)}</td>"
            f"<td>{html.escape(u.username)}</td><td>{html.escape(u.email)}</td><td>{html.escape(services)}</td></tr>"
        )
    return f"<table><thead><tr><th>Discord ID</th><th>Discord name</th><th>Username</th><th>Email</th><th>Services</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


async def get_index(request: web.Request) -> web.Response:
    """Serve the login page, or redirect to the dashboard if already logged in."""
    if _session_username(request):
        return web.Response(status=302, headers={"Location": "/admin/dashboard"})
    return web.Response(text=_login_page(), content_type="text/html")


async def post_login(request: web.Request) -> web.Response:
    """Handle admin login form submission.

    On first use (no login file), creates the initial admin account from the
    submitted credentials. On subsequent requests, verifies against the stored
    credentials (including pending admin first-login flow).

    Form fields:
        username: Admin username.
        password: Admin password (plaintext; verified against bcrypt hash).

    Returns:
        Redirect to /admin/dashboard on success, or login page with error.
    """
    try:
        data = await request.post()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
    except Exception:
        return web.Response(
            text=_login_page(error="Invalid request"), content_type="text/html"
        )

    login_path = _get_login_path(request)
    if not auth.auth_file_exists(login_path):
        if username and password:
            auth.first_login_setup(login_path, username, password)
            token = auth.create_session(username)
            resp = web.Response(status=302, headers={"Location": "/admin/dashboard"})
            resp.set_cookie(
                auth.SESSION_COOKIE_NAME,
                token,
                max_age=auth.SESSION_TTL_SECONDS,
                httponly=True,
                samesite="Strict",
            )
            return resp
        return web.Response(
            text=_login_page(
                error="Set a username and password to create the first admin account."
            ),
            content_type="text/html",
        )

    canonical = auth.verify_login(login_path, username, password)
    if not canonical:
        return web.Response(
            text=_login_page(error="Invalid username or password."),
            content_type="text/html",
        )

    token = auth.create_session(canonical)
    resp = web.Response(status=302, headers={"Location": "/admin/dashboard"})
    resp.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="Lax",
    )
    return resp


async def get_logout(request: web.Request) -> web.Response:
    """Invalidate the current session and redirect to the login page."""
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    auth.drop_session(token)
    resp = web.Response(status=302, headers={"Location": "/admin/"})
    resp.del_cookie(auth.SESSION_COOKIE_NAME)
    return resp


@_login_required
async def get_dashboard(request: web.Request) -> web.Response:
    """Render the main admin dashboard with the current users table."""
    html_content = _dashboard_page(request)
    # Replace users placeholder with actual table
    users_table = await _render_users_table(request)
    html_content = html_content.replace(
        '<div id="users-content">Loading...</div>',
        f'<div id="users-content">{users_table}</div>',
    )
    return web.Response(text=html_content, content_type="text/html")


@_login_required
async def post_send_help(request: web.Request) -> web.Response:
    """Send the /help embed to a Discord user by ID via DM.

    Form fields:
        discord_id: Snowflake ID of the target Discord user.
    """
    try:
        data = await request.post()
        raw_id = (data.get("discord_id") or "").strip()
        discord_id = int(raw_id)
    except (ValueError, TypeError):
        return web.Response(
            text=_dashboard_page(
                request, active_tab="sendhelp", error="Invalid Discord ID."
            ),
            content_type="text/html",
        )

    bot = _get_bot(request)
    if not bot:
        return web.Response(
            text=_dashboard_page(
                request, active_tab="sendhelp", error="Bot not available."
            ),
            content_type="text/html",
        )
    cog = bot.get_cog("Registration")
    if not cog:
        return web.Response(
            text=_dashboard_page(
                request, active_tab="sendhelp", error="Registration cog not loaded."
            ),
            content_type="text/html",
        )

    try:
        user = await bot.fetch_user(discord_id)
        if not user:
            return web.Response(
                text=_dashboard_page(
                    request, active_tab="sendhelp", error="User not found."
                ),
                content_type="text/html",
            )
        dm = await user.create_dm()
        embed = cog._create_full_help_embed()
        await dm.send(embed=embed)
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="sendhelp",
                message=f"Help message sent to {user} (ID {discord_id}).",
            ),
            content_type="text/html",
        )
    except discord.Forbidden:
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="sendhelp",
                error="Cannot DM that user (DMs disabled or blocked).",
            ),
            content_type="text/html",
        )
    except Exception:
        logger.exception("Send help failed for Discord ID %s", discord_id)
        return web.Response(
            text=_dashboard_page(request, active_tab="sendhelp", error="Failed to send help message. Check server logs for details."),
            content_type="text/html",
        )


@_login_required
async def post_send_message(request: web.Request) -> web.Response:
    """Send a custom message to one user or all registered users; optionally to Jellyfin sessions."""
    try:
        data = await request.post()
        target = (data.get("target") or "one").strip().lower()
        if target not in ("one", "all"):
            target = "one"
        message = (data.get("message") or "").strip()
        if not message:
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="sendmessage",
                    error="Message is required.",
                ),
                content_type="text/html",
            )
        header = (data.get("header") or "").strip() or "Message from Monolith"
        send_to_jellyfin = data.get("send_to_jellyfin") == "1"
    except Exception:
        logger.warning("Failed to parse send-message form data", exc_info=True)
        return web.Response(
            text=_dashboard_page(request, active_tab="sendmessage", error="Invalid request."),
            content_type="text/html",
        )

    bot = _get_bot(request)
    if not bot:
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="sendmessage",
                error="Bot not available.",
            ),
            content_type="text/html",
        )

    if target == "one":
        try:
            raw_id = (data.get("discord_id") or "").strip()
            discord_id = int(raw_id)
        except (ValueError, TypeError):
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="sendmessage",
                    error="Invalid Discord ID.",
                ),
                content_type="text/html",
            )
        try:
            user = await bot.fetch_user(discord_id)
            if not user:
                return web.Response(
                    text=_dashboard_page(
                        request,
                        active_tab="sendmessage",
                        error="User not found.",
                    ),
                    content_type="text/html",
                )
            dm = await user.create_dm()
            embed = discord.Embed(
                title=header,
                description=message,
                color=discord.Color.blue(),
            )
            await dm.send(embed=embed)
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="sendmessage",
                    message=f"Message sent to {user} (ID {discord_id}).",
                ),
                content_type="text/html",
            )
        except discord.Forbidden:
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="sendmessage",
                    error="Cannot DM that user (DMs disabled or blocked).",
                ),
                content_type="text/html",
            )
        except Exception:
            logger.exception("Send message failed for Discord ID %s", discord_id)
            return web.Response(
                text=_dashboard_page(request, active_tab="sendmessage", error="Failed to send message. Check server logs for details."),
                content_type="text/html",
            )

    # target == "all"
    cog = bot.get_cog("Registration")
    registry = getattr(cog, "user_registry", None) if cog else None
    if not registry:
        if not send_to_jellyfin or not getattr(bot, "jellyfin_service", None):
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="sendmessage",
                    error="Registration not loaded or no user registry.",
                ),
                content_type="text/html",
            )
        users = []
    else:
        users = registry.get_all_users()

    sent_discord = 0
    failed_discord: list[str] = []
    for u in users:
        try:
            discord_user = await bot.fetch_user(u.discord_id)
            if not discord_user:
                failed_discord.append(str(u.discord_id))
                continue
            dm = await discord_user.create_dm()
            embed = discord.Embed(
                title=header,
                description=message,
                color=discord.Color.blue(),
            )
            await dm.send(embed=embed)
            sent_discord += 1
        except discord.Forbidden:
            failed_discord.append(u.discord_name or str(u.discord_id))
        except Exception as e:
            logger.warning("Send message to %s failed: %s", u.discord_id, e)
            failed_discord.append(u.discord_name or str(u.discord_id))
        await asyncio.sleep(0.5)

    sent_jellyfin = 0
    jellyfin_error = ""
    if send_to_jellyfin and getattr(bot, "jellyfin_service", None):
        try:
            jellyfin = bot.jellyfin_service
            sessions = await jellyfin.get_sessions()
            for s in sessions:
                sid = s.get("Id")
                if not sid:
                    continue
                try:
                    await jellyfin.send_session_message(sid, header, message)
                    sent_jellyfin += 1
                except Exception as e:
                    logger.warning("Jellyfin session %s message failed: %s", sid, e)
        except Exception as e:
            logger.exception("Jellyfin send message failed")
            jellyfin_error = f" Jellyfin: {e}"

    parts = [f"Discord: sent to {sent_discord} users."]
    if failed_discord:
        parts.append(f" Failed for {len(failed_discord)}.")
    if send_to_jellyfin:
        parts.append(f" Jellyfin: sent to {sent_jellyfin} sessions.")
    if jellyfin_error:
        parts.append(jellyfin_error)
    summary = "".join(parts)
    return web.Response(
        text=_dashboard_page(
            request,
            active_tab="sendmessage",
            message=summary,
        ),
        content_type="text/html",
    )


@_login_required
async def post_password_reset(request: web.Request) -> web.Response:
    """Reset a registered user's password across all services and DM them the new one.

    Looks the user up by their Monolith username (not Discord ID), delegates to
    RegistrationService.reset_password(), and attempts to DM the result. DM
    failures are logged and noted in the success message but do not fail the action.

    Form fields:
        username: The Monolith username of the user to reset.
    """
    try:
        data = await request.post()
        username = (data.get("username") or "").strip()
        if not username:
            raise ValueError("Username required")
    except Exception as e:
        return web.Response(
            text=_dashboard_page(request, active_tab="reset", error=str(e)),
            content_type="text/html",
        )

    bot = _get_bot(request)
    if not bot:
        return web.Response(
            text=_dashboard_page(
                request, active_tab="reset", error="Bot not available."
            ),
            content_type="text/html",
        )
    cog = bot.get_cog("Registration")
    if (
        not cog
        or not getattr(cog, "user_registry", None)
        or not getattr(cog, "registration_service", None)
    ):
        return web.Response(
            text=_dashboard_page(
                request, active_tab="reset", error="Registration not available."
            ),
            content_type="text/html",
        )

    registry = cog.user_registry
    user = registry.get_by_username(username)
    if not user:
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="reset",
                error=f"No registered user with username {username!r}.",
            ),
            content_type="text/html",
        )

    try:
        result = await cog.registration_service.reset_password(user.username)
        if not result.any_success:
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="reset",
                    error="Password reset failed on all services.",
                ),
                content_type="text/html",
            )
        discord_user = await bot.fetch_user(user.discord_id)
        dm_note = ""
        if discord_user:
            try:
                dm = await discord_user.create_dm()
                await dm.send(
                    f"Your Monolith password has been reset. New password (save it): **{result.password}**"
                )
            except discord.Forbidden:
                logger.warning(
                    "Could not DM user %s after password reset (DMs disabled)", user.discord_id
                )
                dm_note = " (DM failed — user has DMs disabled)"
            except Exception:
                logger.warning("Failed to DM user %s after password reset", user.discord_id, exc_info=True)
                dm_note = " (DM could not be delivered)"
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="reset",
                message=f"Password reset for {username}. New password sent via DM.{dm_note}",
            ),
            content_type="text/html",
        )
    except Exception:
        logger.exception("Password reset failed for username %r", username)
        return web.Response(
            text=_dashboard_page(request, active_tab="reset", error="Password reset failed. Check server logs for details."),
            content_type="text/html",
        )


@_login_required
async def post_register(request: web.Request) -> web.Response:
    """Register a user on all services on their behalf, then DM them the result.

    Adds the user to the registry keyed by Discord ID. DM failures are logged
    and noted in the success message but do not fail the action.

    Form fields:
        discord_id: Snowflake ID of the Discord user to register.
        username:   Desired Monolith username.
        email:      User's email address.
    """
    try:
        data = await request.post()
        raw_id = (data.get("discord_id") or "").strip()
        discord_id = int(raw_id)
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip()
        if not username or not email:
            raise ValueError("Username and email required")
    except (ValueError, TypeError) as e:
        return web.Response(
            text=_dashboard_page(request, active_tab="register", error=str(e)),
            content_type="text/html",
        )

    bot = _get_bot(request)
    if not bot:
        return web.Response(
            text=_dashboard_page(
                request, active_tab="register", error="Bot not available."
            ),
            content_type="text/html",
        )
    cog = bot.get_cog("Registration")
    if (
        not cog
        or not getattr(cog, "user_registry", None)
        or not getattr(cog, "registration_service", None)
    ):
        return web.Response(
            text=_dashboard_page(
                request, active_tab="register", error="Registration not available."
            ),
            content_type="text/html",
        )

    try:
        result = await cog.registration_service.register_user(username, email)
        if not result.any_success:
            return web.Response(
                text=_dashboard_page(
                    request,
                    active_tab="register",
                    error="Registration failed on all services.",
                ),
                content_type="text/html",
            )
        services = [sr.service_name for sr in result.services if sr.success]
        discord_user = None
        try:
            discord_user = await bot.fetch_user(discord_id)
        except discord.NotFound:
            logger.warning("Discord user %s not found when registering on behalf", discord_id)
        except Exception:
            logger.warning("Failed to fetch Discord user %s during registration", discord_id, exc_info=True)
        discord_name = str(discord_user) if discord_user else str(discord_id)
        if cog.user_registry.is_discord_user_registered(discord_id):
            cog.user_registry.update_services(discord_id, services)
        else:
            cog.user_registry.add_user(
                discord_id=discord_id,
                discord_name=discord_name,
                username=username,
                email=email,
                services=services,
            )
        await cog.user_registry.save()
        dm_note = ""
        if discord_user:
            try:
                dm = await discord_user.create_dm()
                embed = cog._create_result_embed(result)
                await dm.send(embed=embed)
            except discord.Forbidden:
                logger.warning("Could not DM user %s after registration (DMs disabled)", discord_id)
                dm_note = " (DM failed — user has DMs disabled)"
            except Exception:
                logger.warning("Failed to DM user %s after registration", discord_id, exc_info=True)
                dm_note = " (DM could not be delivered)"
        else:
            dm_note = " (Discord user not found — no DM sent)"
        return web.Response(
            text=_dashboard_page(
                request,
                active_tab="register",
                message=f"Registered {username}.{dm_note}",
            ),
            content_type="text/html",
        )
    except Exception:
        logger.exception("Register on behalf failed for username %r", username)
        return web.Response(
            text=_dashboard_page(request, active_tab="register", error="Registration failed. Check server logs for details."),
            content_type="text/html",
        )


@_login_required
async def post_add_admin(request: web.Request) -> web.Response:
    """Add a username to the pending admins list (initial admin only).

    The named user can log in once to claim their account and set a password.
    Only the initial admin (the one who set up the login file) may call this.

    Form fields:
        username: The username to add as a pending admin.
    """
    try:
        data = await request.post()
        new_username = (data.get("username") or "").strip()
        if not new_username:
            raise ValueError("Username required")
    except Exception:
        logger.warning("Failed to parse add-admin form data", exc_info=True)
        return web.Response(
            text=_dashboard_page(request, active_tab="admins", error="Invalid request."),
            content_type="text/html",
        )

    by_username = request["admin_username"]
    login_path = _get_login_path(request)
    ok, msg = auth.add_pending_admin(login_path, new_username, by_username)
    if ok:
        return web.Response(
            text=_dashboard_page(request, active_tab="admins", message=msg),
            content_type="text/html",
        )
    return web.Response(
        text=_dashboard_page(request, active_tab="admins", error=msg),
        content_type="text/html",
    )


async def get_root(_request: web.Request) -> web.StreamResponse:
    """Redirect root to admin UI."""
    return web.HTTPFound("/admin/")


def create_app(
    bot: Optional["MonolithBot"] = None, config: Any = None
) -> web.Application:
    """Create and configure the aiohttp admin UI application.

    Registers all admin routes and stores the bot and config references in
    the app registry so route handlers can access them via ``_get_bot()`` and
    ``_get_config()``.

    Args:
        bot: The running MonolithBot instance. May be None during testing.
        config: The bot Config object. May be None during testing; handlers
            will fall back to default paths (e.g., ``data/admin-login.json``).

    Returns:
        A configured ``web.Application`` ready to be started with a runner.
    """
    app = web.Application()
    app[APP_KEY_BOT] = bot
    app[APP_KEY_CONFIG] = config

    app.router.add_get("/", get_root)
    app.router.add_get("/admin/", get_index)
    app.router.add_get("/admin", get_index)
    app.router.add_post("/admin/login", post_login)
    app.router.add_get("/admin/logout", get_logout)
    app.router.add_get("/admin/dashboard", get_dashboard)
    app.router.add_post("/admin/action/send-help", post_send_help)
    app.router.add_post("/admin/action/send-message", post_send_message)
    app.router.add_post("/admin/action/password-reset", post_password_reset)
    app.router.add_post("/admin/action/register", post_register)
    app.router.add_post("/admin/action/add-admin", post_add_admin)

    return app

"""
aiohttp application for the admin UI.

Serves login, dashboard with tabs (Users, Send help, Password reset,
Register on behalf, Manage admins), and action handlers. Expects bot
and config to be set on the app instance after creation.
"""

from __future__ import annotations

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
    return request.app.get(APP_KEY_BOT)


def _get_config(request: web.Request):
    return request.app.get(APP_KEY_CONFIG)


def _get_login_path(request: web.Request) -> str:
    cfg = _get_config(request)
    return (cfg and cfg.admin_ui.admin_login_file) or "data/admin-login.json"


def _session_username(request: web.Request) -> Optional[str]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    return auth.get_session(token)


def _login_required(handler):
    async def wrapper(request: web.Request):
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
    return _base_html("Admin Login", f"""
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
""")


def _dashboard_page(request: web.Request, active_tab: str = "users", message: str = "", error: str = "") -> str:
    username = request["admin_username"]
    is_initial = auth.is_initial_admin(_get_login_path(request), username)
    msg_html = f'<div class="msg success">{html.escape(message)}</div>' if message else ""
    err_html = f'<div class="msg error">{html.escape(error)}</div>' if error else ""

    tabs = [
        ('users', 'Users'),
        ('sendhelp', 'Send help'),
        ('reset', 'Password reset'),
        ('register', 'Register user'),
    ]
    if is_initial:
        tabs.append(('admins', 'Manage admins'))

    tab_links = "".join(
        f'<a href="#" class="tab-link {"active" if t[0] == active_tab else ""}" data-tab="{t[0]}">{html.escape(t[1])}</a>'
        for t in tabs
    )

    return _base_html("Admin Dashboard", f"""
<div class="header">
<h1>MonolithBot Admin</h1>
<span>Logged in as <strong>{html.escape(username)}</strong> | <a href="/admin/logout">Log out</a></span>
</div>
{msg_html}
{err_html}
<nav class="tabs" role="tablist">{tab_links}</nav>

<div id="panel-users" class="panel {'active' if active_tab == 'users' else ''}" data-tab="users">
<h2>Registered users</h2>
<div id="users-content">Loading...</div>
</div>

<div id="panel-sendhelp" class="panel {'active' if active_tab == 'sendhelp' else ''}" data-tab="sendhelp">
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

<div id="panel-reset" class="panel {'active' if active_tab == 'reset' else ''}" data-tab="reset">
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

<div id="panel-register" class="panel {'active' if active_tab == 'register' else ''}" data-tab="register">
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

<div id="panel-admins" class="panel {'active' if active_tab == 'admins' else ''}" data-tab="admins">
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
</script>
""")


async def _render_users_table(request: web.Request) -> str:
    bot = _get_bot(request)
    if not bot:
        return "<p>Bot not available.</p>"
    cog = bot.get_cog("Registration")
    if not cog or not getattr(cog, "user_registry", None):
        return "<p>Registration not loaded or no user registry.</p>"
    registry = cog.user_registry
    await registry.load()
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
    if _session_username(request):
        return web.Response(status=302, headers={"Location": "/admin/dashboard"})
    return web.Response(text=_login_page(), content_type="text/html")


async def post_login(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
    except Exception:
        return web.Response(text=_login_page(error="Invalid request"), content_type="text/html")

    login_path = _get_login_path(request)
    if not auth.auth_file_exists(login_path):
        if username and password:
            auth.first_login_setup(login_path, username, password)
            token = auth.create_session(username)
            resp = web.Response(status=302, headers={"Location": "/admin/dashboard"})
            resp.set_cookie(auth.SESSION_COOKIE_NAME, token, max_age=auth.SESSION_TTL_SECONDS, httponly=True, samesite="Lax")
            return resp
        return web.Response(text=_login_page(error="Set a username and password to create the first admin account."), content_type="text/html")

    canonical = auth.verify_login(login_path, username, password)
    if not canonical:
        return web.Response(text=_login_page(error="Invalid username or password."), content_type="text/html")

    token = auth.create_session(canonical)
    resp = web.Response(status=302, headers={"Location": "/admin/dashboard"})
    resp.set_cookie(auth.SESSION_COOKIE_NAME, token, max_age=auth.SESSION_TTL_SECONDS, httponly=True, samesite="Lax")
    return resp


async def get_logout(request: web.Request) -> web.Response:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    auth.drop_session(token)
    resp = web.Response(status=302, headers={"Location": "/admin/"})
    resp.del_cookie(auth.SESSION_COOKIE_NAME)
    return resp


@_login_required
async def get_dashboard(request: web.Request) -> web.Response:
    html_content = _dashboard_page(request)
    # Replace users placeholder with actual table
    users_table = await _render_users_table(request)
    html_content = html_content.replace("<div id=\"users-content\">Loading...</div>", f"<div id=\"users-content\">{users_table}</div>")
    return web.Response(text=html_content, content_type="text/html")


@_login_required
async def post_send_help(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        raw_id = (data.get("discord_id") or "").strip()
        discord_id = int(raw_id)
    except (ValueError, TypeError):
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error="Invalid Discord ID."), content_type="text/html")

    bot = _get_bot(request)
    if not bot:
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error="Bot not available."), content_type="text/html")
    cog = bot.get_cog("Registration")
    if not cog:
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error="Registration cog not loaded."), content_type="text/html")

    try:
        user = await bot.fetch_user(discord_id)
        if not user:
            return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error="User not found."), content_type="text/html")
        dm = await user.create_dm()
        embed = cog._create_full_help_embed()
        await dm.send(embed=embed)
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", message=f"Help message sent to {user} (ID {discord_id})."), content_type="text/html")
    except discord.Forbidden:
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error="Cannot DM that user (DMs disabled or blocked)."), content_type="text/html")
    except Exception as e:
        logger.exception("Send help failed")
        return web.Response(text=_dashboard_page(request, active_tab="sendhelp", error=str(e)), content_type="text/html")


@_login_required
async def post_password_reset(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        username = (data.get("username") or "").strip()
        if not username:
            raise ValueError("Username required")
    except Exception as e:
        return web.Response(text=_dashboard_page(request, active_tab="reset", error=str(e)), content_type="text/html")

    bot = _get_bot(request)
    if not bot:
        return web.Response(text=_dashboard_page(request, active_tab="reset", error="Bot not available."), content_type="text/html")
    cog = bot.get_cog("Registration")
    if not cog or not getattr(cog, "user_registry", None) or not getattr(cog, "registration_service", None):
        return web.Response(text=_dashboard_page(request, active_tab="reset", error="Registration not available."), content_type="text/html")

    registry = cog.user_registry
    await registry.load()
    user = registry.get_by_username(username)
    if not user:
        return web.Response(text=_dashboard_page(request, active_tab="reset", error=f"No registered user with username {username!r}."), content_type="text/html")

    try:
        result = await cog.registration_service.reset_password(user.username)
        if not result.any_success:
            return web.Response(text=_dashboard_page(request, active_tab="reset", error="Password reset failed on all services."), content_type="text/html")
        discord_user = await bot.fetch_user(user.discord_id)
        if discord_user:
            try:
                dm = await discord_user.create_dm()
                await dm.send(f"Your Monolith password has been reset. New password (save it): **{result.password}**")
            except Exception:
                pass
        return web.Response(text=_dashboard_page(request, active_tab="reset", message=f"Password reset for {username}. New password sent via DM."), content_type="text/html")
    except Exception as e:
        logger.exception("Password reset failed")
        return web.Response(text=_dashboard_page(request, active_tab="reset", error=str(e)), content_type="text/html")


@_login_required
async def post_register(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        raw_id = (data.get("discord_id") or "").strip()
        discord_id = int(raw_id)
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip()
        if not username or not email:
            raise ValueError("Username and email required")
    except (ValueError, TypeError) as e:
        return web.Response(text=_dashboard_page(request, active_tab="register", error=str(e)), content_type="text/html")

    bot = _get_bot(request)
    if not bot:
        return web.Response(text=_dashboard_page(request, active_tab="register", error="Bot not available."), content_type="text/html")
    cog = bot.get_cog("Registration")
    if not cog or not getattr(cog, "user_registry", None) or not getattr(cog, "registration_service", None):
        return web.Response(text=_dashboard_page(request, active_tab="register", error="Registration not available."), content_type="text/html")

    try:
        result = await cog.registration_service.register_user(username, email)
        if not result.any_success:
            return web.Response(text=_dashboard_page(request, active_tab="register", error="Registration failed on all services."), content_type="text/html")
        services = [sr.service_name for sr in result.services if sr.success]
        discord_user = None
        try:
            discord_user = await bot.fetch_user(discord_id)
        except Exception:
            pass
        discord_name = str(discord_user) if discord_user else str(discord_id)
        if cog.user_registry.is_discord_user_registered(discord_id):
            cog.user_registry.update_services(discord_id, services)
        else:
            cog.user_registry.add_user(discord_id=discord_id, discord_name=discord_name, username=username, email=email, services=services)
        await cog.user_registry.save()
        if discord_user:
            try:
                dm = await discord_user.create_dm()
                embed = cog._create_result_embed(result)
                await dm.send(embed=embed)
            except Exception:
                pass
        return web.Response(text=_dashboard_page(request, active_tab="register", message=f"Registered {username} and sent result via DM."), content_type="text/html")
    except Exception as e:
        logger.exception("Register on behalf failed")
        return web.Response(text=_dashboard_page(request, active_tab="register", error=str(e)), content_type="text/html")


@_login_required
async def post_add_admin(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        new_username = (data.get("username") or "").strip()
        if not new_username:
            raise ValueError("Username required")
    except Exception as e:
        return web.Response(text=_dashboard_page(request, active_tab="admins", error=str(e)), content_type="text/html")

    by_username = request["admin_username"]
    login_path = _get_login_path(request)
    ok, msg = auth.add_pending_admin(login_path, new_username, by_username)
    if ok:
        return web.Response(text=_dashboard_page(request, active_tab="admins", message=msg), content_type="text/html")
    return web.Response(text=_dashboard_page(request, active_tab="admins", error=msg), content_type="text/html")


async def get_root(_request: web.Request) -> web.StreamResponse:
    """Redirect root to admin UI."""
    return web.HTTPFound("/admin/")


def create_app(bot: Optional["MonolithBot"] = None, config: Any = None) -> web.Application:
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
    app.router.add_post("/admin/action/password-reset", post_password_reset)
    app.router.add_post("/admin/action/register", post_register)
    app.router.add_post("/admin/action/add-admin", post_add_admin)

    return app

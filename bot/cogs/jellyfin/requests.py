"""
Content request cog for MonolithBot.

Provides the /jf-request command, allowing users to request movies and TV shows
be added to the media server by supplying an IMDB or TVDB link.

Movies are added via Radarr; TV series are added via Sonarr. Content type is
determined by querying both services' own lookup endpoints — no additional API
keys are required.

Supported URL formats:
    IMDB:
        https://www.imdb.com/title/tt0133093/
        https://imdb.com/title/tt0133093
    TVDB (numeric ID only):
        https://www.thetvdb.com/series/295759
        https://thetvdb.com/dereferrer/series/295759

Slash Commands:
    /jf-request - Request a movie or TV show to be added to the library

Configuration:
    Requires at least one of the following to be enabled in config:
        - radarr (for movie requests)
        - sonarr (for TV show requests)

See Also:
    - bot.services.radarr: Radarr API client
    - bot.services.sonarr: Sonarr API client
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.radarr import (
    RadarrExistsError,
    RadarrMovie,
    RadarrError,
)
from bot.services.sonarr import (
    SonarrExistsError,
    SonarrSeries,
    SonarrError,
)

if TYPE_CHECKING:
    from bot.main import MonolithBot

logger = logging.getLogger("monolithbot.requests")

# =============================================================================
# URL Parsing
# =============================================================================

# Matches: imdb.com/title/tt1234567 (with or without trailing path/slash)
IMDB_PATTERN = re.compile(r"imdb\.com/title/(tt\d+)", re.IGNORECASE)

# Matches TVDB URLs that contain a numeric series ID:
#   thetvdb.com/series/295759
#   thetvdb.com/series/295759/episodes/...
#   thetvdb.com/dereferrer/series/295759
TVDB_NUMERIC_PATTERN = re.compile(
    r"thetvdb\.com/(?:dereferrer/)?series/(\d+)", re.IGNORECASE
)

# Matches TVDB URLs with a text slug (e.g. /series/game-of-thrones).
# These cannot be used directly — we detect them to provide a helpful error.
TVDB_SLUG_PATTERN = re.compile(
    r"thetvdb\.com/series/([a-zA-Z][a-zA-Z0-9\-]*)", re.IGNORECASE
)

# =============================================================================
# Embed Helpers
# =============================================================================

MAX_OVERVIEW_LENGTH = 200


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def _movie_added_embed(movie: RadarrMovie) -> discord.Embed:
    title = f"{movie.title} ({movie.year})" if movie.year else movie.title
    embed = discord.Embed(
        title=title,
        description=_truncate(movie.overview, MAX_OVERVIEW_LENGTH) if movie.overview else None,
        color=discord.Color.green(),
    )
    embed.set_footer(text="Added to Radarr \u2014 movie download queued")
    if movie.remote_poster:
        embed.set_thumbnail(url=movie.remote_poster)
    return embed


def _series_added_embed(series: SonarrSeries) -> discord.Embed:
    title = f"{series.title} ({series.year})" if series.year else series.title
    embed = discord.Embed(
        title=title,
        description=_truncate(series.overview, MAX_OVERVIEW_LENGTH) if series.overview else None,
        color=discord.Color.green(),
    )
    embed.set_footer(text="Added to Sonarr \u2014 episode search queued")
    if series.remote_poster:
        embed.set_thumbnail(url=series.remote_poster)
    return embed


def _already_exists_embed(name: str, media_type: str) -> discord.Embed:
    return discord.Embed(
        title=f"{name} is already in the library",
        description=f"This {media_type} has already been added to the request queue.",
        color=discord.Color.yellow(),
    )


def _not_found_embed(link: str) -> discord.Embed:
    return discord.Embed(
        title="Not found",
        description=(
            f"No results were found for that link in Radarr or Sonarr. "
            f"The content may not be in the metadata databases yet, or the link may be incorrect.\n\n"
            f"Link provided: `{link}`"
        ),
        color=discord.Color.red(),
    )


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="Request failed",
        description=message,
        color=discord.Color.red(),
    )


# =============================================================================
# Cog
# =============================================================================


class ContentRequestCog(commands.Cog, name="ContentRequests"):
    """
    Discord cog providing the /jf-request content request command.

    Allows any guild member to request a movie or TV show by supplying
    an IMDB or TVDB link. The bot routes the request to Radarr (movies)
    or Sonarr (TV shows) based on which service recognizes the content.

    Attributes:
        bot: Reference to the MonolithBot instance.
    """

    def __init__(self, bot: "MonolithBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="jf-request",
        description="Request a movie or TV show to be added to the media library",
    )
    @app_commands.describe(link="IMDB or TVDB link to the movie or show")
    async def request_command(
        self, interaction: discord.Interaction, link: str
    ) -> None:
        """
        Handle a content request from a Discord user.

        Accepts an IMDB or TVDB URL, determines whether the content is a
        movie or TV show, and adds it to Radarr or Sonarr accordingly.

        IMDB links are looked up in both Radarr and Sonarr to determine
        the content type (no external API required). TVDB links are sent
        directly to Sonarr.
        """
        await interaction.response.defer()

        link = link.strip()

        # --- Detect URL type ---
        imdb_match = IMDB_PATTERN.search(link)
        tvdb_numeric_match = TVDB_NUMERIC_PATTERN.search(link)
        tvdb_slug_match = TVDB_SLUG_PATTERN.search(link) if not tvdb_numeric_match else None

        if tvdb_slug_match and not tvdb_numeric_match:
            await interaction.followup.send(
                embed=_error_embed(
                    "TVDB slug URLs aren\u2019t supported. Please use a TVDB URL with a "
                    "numeric series ID (e.g. `thetvdb.com/series/295759`) or use an IMDB "
                    "link instead."
                )
            )
            return

        if not imdb_match and not tvdb_numeric_match:
            await interaction.followup.send(
                embed=_error_embed(
                    "Please provide a valid IMDB link (e.g. `imdb.com/title/tt0133093`) "
                    "or a TVDB link with a numeric series ID "
                    "(e.g. `thetvdb.com/series/295759`)."
                )
            )
            return

        radarr = self.bot.radarr_service
        sonarr = self.bot.sonarr_service

        # --- TVDB link: always goes to Sonarr ---
        if tvdb_numeric_match:
            if not sonarr:
                await interaction.followup.send(
                    embed=_error_embed(
                        "Sonarr is not enabled. TVDB links can only be used to add TV shows."
                    )
                )
                return

            tvdb_id = int(tvdb_numeric_match.group(1))
            await self._handle_tvdb_request(interaction, sonarr, tvdb_id)
            return

        # --- IMDB link: look up in Radarr and/or Sonarr ---
        imdb_id = imdb_match.group(1)
        await self._handle_imdb_request(interaction, radarr, sonarr, imdb_id, link)

    async def _handle_tvdb_request(
        self,
        interaction: discord.Interaction,
        sonarr,
        tvdb_id: int,
    ) -> None:
        """Look up a TVDB ID in Sonarr and add it."""
        try:
            results = await sonarr.lookup_by_tvdb(tvdb_id)
        except SonarrError as e:
            logger.error(f"Sonarr lookup failed for TVDB {tvdb_id}: {e}")
            await interaction.followup.send(
                embed=_error_embed(f"Could not reach Sonarr: {e}")
            )
            return

        if not results:
            await interaction.followup.send(
                embed=_error_embed(
                    f"No series found for TVDB ID `{tvdb_id}`. "
                    f"The show may not be in the Sonarr metadata database yet."
                )
            )
            return

        series_result = results[0]
        try:
            series = await sonarr.add_series(series_result.raw)
            await interaction.followup.send(embed=_series_added_embed(series))
        except SonarrExistsError as e:
            name = e.series.title if e.series else f"TVDB {tvdb_id}"
            await interaction.followup.send(
                embed=_already_exists_embed(name, "TV show")
            )
        except SonarrError as e:
            logger.error(f"Sonarr add failed for TVDB {tvdb_id}: {e}")
            await interaction.followup.send(
                embed=_error_embed(f"Failed to add to Sonarr: {e}")
            )

    async def _handle_imdb_request(
        self,
        interaction: discord.Interaction,
        radarr,
        sonarr,
        imdb_id: str,
        original_link: str,
    ) -> None:
        """
        Look up an IMDB ID in Radarr and/or Sonarr, then add the content.

        When both services are enabled, both lookups run in parallel. Radarr
        results are preferred (movies are checked first); Sonarr results are
        used if Radarr finds nothing.
        """
        movie_results: list[RadarrMovie] = []
        series_results: list[SonarrSeries] = []
        radarr_error: Optional[Exception] = None
        sonarr_error: Optional[Exception] = None

        # Run available lookups in parallel
        lookup_tasks = {}
        if radarr:
            lookup_tasks["radarr"] = radarr.lookup_movie(imdb_id)
        if sonarr:
            lookup_tasks["sonarr"] = sonarr.lookup_by_imdb(imdb_id)

        if not lookup_tasks:
            await interaction.followup.send(
                embed=_error_embed("Neither Radarr nor Sonarr is enabled.")
            )
            return

        results = await asyncio.gather(*lookup_tasks.values(), return_exceptions=True)
        result_map = dict(zip(lookup_tasks.keys(), results))

        if "radarr" in result_map:
            val = result_map["radarr"]
            if isinstance(val, Exception):
                radarr_error = val
                logger.warning(f"Radarr lookup failed for {imdb_id}: {val}")
            else:
                movie_results = val

        if "sonarr" in result_map:
            val = result_map["sonarr"]
            if isinstance(val, Exception):
                sonarr_error = val
                logger.warning(f"Sonarr lookup failed for {imdb_id}: {val}")
            else:
                series_results = val

        # Both lookups failed
        if radarr_error and sonarr_error and not movie_results and not series_results:
            await interaction.followup.send(
                embed=_error_embed(
                    "Could not reach Radarr or Sonarr. Please try again later."
                )
            )
            return

        # Radarr found a movie — add it
        if movie_results:
            movie_result = movie_results[0]
            try:
                movie = await radarr.add_movie(movie_result.raw)
                await interaction.followup.send(embed=_movie_added_embed(movie))
            except RadarrExistsError as e:
                name = e.movie.title if e.movie else imdb_id
                await interaction.followup.send(
                    embed=_already_exists_embed(name, "movie")
                )
            except RadarrError as e:
                logger.error(f"Radarr add failed for {imdb_id}: {e}")
                await interaction.followup.send(
                    embed=_error_embed(f"Failed to add to Radarr: {e}")
                )
            return

        # Sonarr found a series — add it
        if series_results:
            series_result = series_results[0]
            try:
                series = await sonarr.add_series(series_result.raw)
                await interaction.followup.send(embed=_series_added_embed(series))
            except SonarrExistsError as e:
                name = e.series.title if e.series else imdb_id
                await interaction.followup.send(
                    embed=_already_exists_embed(name, "TV show")
                )
            except SonarrError as e:
                logger.error(f"Sonarr add failed for {imdb_id}: {e}")
                await interaction.followup.send(
                    embed=_error_embed(f"Failed to add to Sonarr: {e}")
                )
            return

        # Nothing found in either service
        await interaction.followup.send(embed=_not_found_embed(original_link))


async def setup(bot: "MonolithBot") -> None:
    """Load the ContentRequestCog into the bot."""
    await bot.add_cog(ContentRequestCog(bot))

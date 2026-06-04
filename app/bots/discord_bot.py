from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.core.config import settings
from app.core.db import get_connection, init_db, row_to_dict
from app.integrations.google_calendar import (
    build_google_auth_url,
    google_connected,
    google_oauth_configured,
)

logger = logging.getLogger(__name__)


def _normalize_x_username(value: str) -> str:
    """Discord 입력값에서 앞쪽 @와 공백을 제거해 X username만 남깁니다."""
    return value.strip().lstrip("@")


def _create_artist(
    discord_user_id: str,
    name: str,
    x_username: str,
    display_name: str | None,
    notes: str | None,
) -> dict:
    """Discord 사용자 계정에 귀속된 아티스트와 X 출처를 DB에 함께 등록합니다."""
    normalized_x_username = _normalize_x_username(x_username)
    if not normalized_x_username:
        raise ValueError("X username is required.")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artists (discord_user_id, name, display_name, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (discord_user_id, name.strip(), display_name, notes),
        )
        artist_id = cursor.fetchone()["id"]
        conn.execute(
            """
            INSERT INTO artist_sources (artist_id, source_type, label, value)
            VALUES (%s, 'x', 'X account', %s)
            """,
            (artist_id, normalized_x_username),
        )
        conn.commit()

        return row_to_dict(
            conn.execute("SELECT * FROM artists WHERE id = %s", (artist_id,)).fetchone()
        )


def _delete_artist(discord_user_id: str, artist_id: int) -> bool:
    """요청한 Discord 사용자가 소유한 아티스트만 삭제합니다."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM artists WHERE id = %s AND discord_user_id = %s",
            (artist_id, discord_user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def _list_artists(discord_user_id: str) -> list[dict]:
    """Discord 사용자에게 등록된 아티스트와 대표 X username 목록을 조회합니다."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.id,
                a.name,
                a.display_name,
                s.value AS x_username
            FROM artists a
            LEFT JOIN artist_sources s
                ON s.artist_id = a.id AND s.source_type = 'x'
            WHERE a.discord_user_id = %s
            ORDER BY a.name
            LIMIT 25
            """
            ,
            (discord_user_id,),
        ).fetchall()


class ScheduleMusicBot(discord.Client):
    """schedule_music 전용 Discord slash command 봇 클라이언트입니다."""

    def __init__(self) -> None:
        """Discord client와 slash command tree를 초기화합니다."""
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        """봇 로그인 직후 DB를 준비하고 slash command를 Discord에 동기화합니다."""
        init_db()
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("discord commands synced to guild %s", settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("discord commands synced globally")


bot = ScheduleMusicBot()


@bot.tree.command(name="artist_add", description="Register an artist and X account.")
@app_commands.describe(
    name="Artist name",
    x_username="X username, with or without @",
    display_name="Optional display name",
    notes="Optional notes",
)
async def artist_add(
    interaction: discord.Interaction,
    name: str,
    x_username: str,
    display_name: str | None = None,
    notes: str | None = None,
) -> None:
    """Discord slash command로 아티스트와 X 계정을 등록합니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        artist = _create_artist(str(interaction.user.id), name, x_username, display_name, notes)
    except Exception as exc:
        logger.exception("artist_add failed")
        await interaction.followup.send(f"Failed to add artist: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        f"Added artist #{artist['id']}: {artist['name']} (@{_normalize_x_username(x_username)})",
        ephemeral=True,
    )


@bot.tree.command(name="artist_list", description="List registered artists.")
async def artist_list(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자가 등록한 아티스트 목록을 보여줍니다."""
    await interaction.response.defer(ephemeral=True)
    artists = _list_artists(str(interaction.user.id))
    if not artists:
        await interaction.followup.send("No artists registered yet.", ephemeral=True)
        return

    lines = []
    for artist in artists:
        display = artist["display_name"] or artist["name"]
        x_username = artist["x_username"]
        suffix = f" (@{x_username})" if x_username else ""
        lines.append(f"#{artist['id']} {display}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="artist_delete", description="Delete an artist by ID.")
@app_commands.describe(artist_id="Artist ID shown by /artist_list")
async def artist_delete(interaction: discord.Interaction, artist_id: int) -> None:
    """현재 Discord 사용자의 아티스트를 ID 기준으로 삭제합니다."""
    await interaction.response.defer(ephemeral=True)
    deleted = _delete_artist(str(interaction.user.id), artist_id)
    if deleted:
        await interaction.followup.send(f"Deleted artist #{artist_id}.", ephemeral=True)
    else:
        await interaction.followup.send(f"Artist #{artist_id} was not found.", ephemeral=True)


@bot.tree.command(name="google_connect", description="Connect your Google Calendar.")
async def google_connect(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자에게 Google Calendar OAuth 연결 링크를 안내합니다."""
    await interaction.response.defer(ephemeral=True)
    if google_connected(str(interaction.user.id)):
        await interaction.followup.send("Google Calendar is already connected.", ephemeral=True)
        return
    if not google_oauth_configured():
        await interaction.followup.send(
            "Google OAuth is not configured on the server yet.",
            ephemeral=True,
        )
        return

    auth_url = build_google_auth_url(str(interaction.user.id))
    await interaction.followup.send(
        f"Connect Google Calendar here:\n{auth_url}",
        ephemeral=True,
    )


async def start_discord_bot() -> None:
    """토큰이 설정되어 있으면 Discord 봇을 시작하고, 없으면 비활성 상태로 둡니다."""
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN is not set; Discord bot is disabled.")
        return

    await bot.start(settings.discord_bot_token)

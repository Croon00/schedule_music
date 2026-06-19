from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from youtube_transcript_api._errors import (
    IpBlocked,
    RequestBlocked,
    TranscriptsDisabled,
    YouTubeTranscriptApiException,
)

from app.core.config import settings
from app.core.db import get_connection, init_db, row_to_dict
from app.integrations.google_calendar import (
    build_google_auth_url,
    google_connected,
    google_oauth_configured,
)
from app.lyrics_pipeline.clients import (
    OpenAiLyricsClient,
    OpenAiSpeechToTextClient,
    YouTubeTranscriptCaptionClient,
    YtDlpAudioDownloader,
)
from app.lyrics_pipeline.models import LyricsInput, RawLyrics
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import extract_youtube_video_id

logger = logging.getLogger(__name__)

LYRICS_SAMPLE_MAX_CHARS = 1000
LYRICS_SAMPLE_MAX_LINES = 1000
LYRICS_EXPORT_DIR = Path("exports")


class _NoopLyricsAiClient:
    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        return "", ""

    async def render_namuwiki(
        self,
        *,
        original: str,
        translation_ko: str,
        pronunciation_ko: str,
        format_example: str,
        artist: str | None,
        title: str | None,
    ) -> str:
        return format_example


def _normalize_x_username(value: str) -> str:
    """Discord 입력값에서 앞쪽 @와 공백을 제거해 X username만 남깁니다."""
    return value.strip().lstrip("@")


def _caption_sample(text: str) -> str:
    lines: list[str] = []
    used_chars = 0
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        remaining = LYRICS_SAMPLE_MAX_CHARS - used_chars
        if remaining <= 0 or len(lines) >= LYRICS_SAMPLE_MAX_LINES:
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
        lines.append(line)
        used_chars += len(line)
    return "\n".join(lines)


def _caption_report(
    *,
    youtube_url: str,
    tracks: list,
    raw: RawLyrics,
    translation_ko: str | None = None,
    pronunciation_ko: str | None = None,
) -> str:
    raw_lines = [line for line in raw.text.splitlines() if line.strip()]
    track_lines = [
        f"- {track.language_code} {track.language_name} generated={track.is_generated}"
        for track in tracks
    ]
    available_captions = chr(10).join(track_lines) if track_lines else "- none"
    sections = [
        f"URL: {youtube_url}",
        f"선택된 출처: {raw.source_type}",
        f"선택된 언어: {raw.language_code}",
        f"검토 필요: {raw.needs_review}",
        f"원문 자막 길이: {len(raw.text)}자 / {len(raw_lines)}줄",
        "",
        "사용 가능한 자막",
        available_captions,
        "",
        "## 원문 미리보기",
        "",
        _caption_sample(raw.text),
    ]
    if translation_ko is not None:
        sections.extend(["", "## 한국어 번역 미리보기", "", translation_ko])
    if pronunciation_ko is not None:
        sections.extend(["", "## 한글 발음 미리보기", "", pronunciation_ko])
    return "\n".join(sections).rstrip() + "\n"


async def _transform_caption_preview(raw: RawLyrics) -> tuple[str | None, str | None]:
    if not settings.openai_api_key:
        return None, None

    preview = _caption_sample(raw.text)
    if not preview:
        return None, None

    ai_client = OpenAiLyricsClient()
    return await ai_client.transform_lyrics(
        lyrics=preview,
        artist=None,
        title=None,
    )


def _openai_status_text(
    translation_ko: str | None,
    pronunciation_ko: str | None,
    error: str | None = None,
) -> str:
    if error:
        return f"OpenAI 미리보기 변환: `실패 ({error})`"
    if translation_ko is None and pronunciation_ko is None:
        return "OpenAI 미리보기 변환: `건너뜀 (OPENAI_API_KEY 미설정)`"
    return "OpenAI 미리보기 변환: `완료`"


def _caption_report_path(video_id: str, discord_user_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return LYRICS_EXPORT_DIR / f"{video_id}_{discord_user_id}_{timestamp}_caption_report.txt"


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
        raise ValueError("X 사용자명은 필수입니다.")

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
            logger.info("Discord 명령어를 길드 %s에 동기화했습니다.", settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("Discord 명령어를 전역으로 동기화했습니다.")


bot = ScheduleMusicBot()


@bot.tree.command(name="artist_add", description="아티스트와 X 계정을 등록합니다.")
@app_commands.describe(
    name="아티스트 이름",
    x_username="@ 포함 여부와 관계없는 X 사용자명",
    display_name="선택 표시 이름",
    notes="선택 메모",
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
        logger.exception("아티스트 등록 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"아티스트 등록에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        f"아티스트 #{artist['id']} 등록 완료: {artist['name']} (@{_normalize_x_username(x_username)})",
        ephemeral=True,
    )


@bot.tree.command(name="artist_list", description="등록된 아티스트 목록을 보여줍니다.")
async def artist_list(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자가 등록한 아티스트 목록을 보여줍니다."""
    await interaction.response.defer(ephemeral=True)
    artists = _list_artists(str(interaction.user.id))
    if not artists:
        await interaction.followup.send("아직 등록된 아티스트가 없습니다.", ephemeral=True)
        return

    lines = []
    for artist in artists:
        display = artist["display_name"] or artist["name"]
        x_username = artist["x_username"]
        suffix = f" (@{x_username})" if x_username else ""
        lines.append(f"#{artist['id']} {display}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="artist_delete", description="ID로 아티스트를 삭제합니다.")
@app_commands.describe(artist_id="/artist_list에 표시된 아티스트 ID")
async def artist_delete(interaction: discord.Interaction, artist_id: int) -> None:
    """현재 Discord 사용자의 아티스트를 ID 기준으로 삭제합니다."""
    await interaction.response.defer(ephemeral=True)
    deleted = _delete_artist(str(interaction.user.id), artist_id)
    if deleted:
        await interaction.followup.send(f"아티스트 #{artist_id}를 삭제했습니다.", ephemeral=True)
    else:
        await interaction.followup.send(f"아티스트 #{artist_id}를 찾지 못했습니다.", ephemeral=True)


@bot.tree.command(name="google_connect", description="Google Calendar를 연결합니다.")
async def google_connect(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자에게 Google Calendar OAuth 연결 링크를 안내합니다."""
    await interaction.response.defer(ephemeral=True)
    if google_connected(str(interaction.user.id)):
        await interaction.followup.send("Google Calendar가 이미 연결되어 있습니다.", ephemeral=True)
        return
    if not google_oauth_configured():
        await interaction.followup.send(
            "서버에 Google OAuth 설정이 아직 없습니다.",
            ephemeral=True,
        )
        return

    auth_url = build_google_auth_url(str(interaction.user.id))
    await interaction.followup.send(
        f"아래 링크에서 Google Calendar를 연결하세요:\n{auth_url}",
        ephemeral=True,
    )


@bot.tree.command(
    name="lyrics_caption_test",
    description="YouTube URL의 수동 자막 추출을 테스트합니다.",
)
@app_commands.describe(
    youtube_url="확인할 YouTube URL",
    audio_fallback="수동 자막이 없을 때 허가된 짧은 오디오 fallback을 사용합니다.",
    language_code="Whisper에 전달할 원문 언어 코드입니다. 예: ja, en, ko",
)
async def lyrics_caption_test(
    interaction: discord.Interaction,
    youtube_url: str,
    audio_fallback: bool = False,
    language_code: str = "ja",
) -> None:
    await interaction.response.defer(ephemeral=True)
    caption_client = YouTubeTranscriptCaptionClient()
    pipeline = LyricsPipeline(
        caption_client=caption_client,
        ai_client=_NoopLyricsAiClient(),
        audio_downloader=YtDlpAudioDownloader() if audio_fallback else None,
        speech_to_text_client=(
            OpenAiSpeechToTextClient(language=language_code.strip() or "ja")
            if audio_fallback
            else None
        ),
    )

    try:
        video_id = extract_youtube_video_id(youtube_url)
        try:
            tracks = await caption_client.list_tracks(video_id)
        except YouTubeTranscriptApiException:
            if not audio_fallback:
                raise
            tracks = []
        raw = await pipeline.get_raw_lyrics(
            LyricsInput(
                youtube_url=youtube_url,
                preferred_languages=(language_code.strip() or "ja", "ja", "en", "ko"),
                allow_audio_fallback=audio_fallback,
            )
        )
        openai_error = None
        try:
            translation_ko, pronunciation_ko = await _transform_caption_preview(raw)
        except Exception as exc:
            logger.exception("가사 미리보기 변환에 실패했습니다.")
            translation_ko, pronunciation_ko = None, None
            openai_error = str(exc)
        report_path = _caption_report_path(video_id, str(interaction.user.id))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _caption_report(
                youtube_url=youtube_url,
                tracks=tracks,
                raw=raw,
                translation_ko=translation_ko,
                pronunciation_ko=pronunciation_ko,
            ),
            encoding="utf-8",
        )
    except ValueError as exc:
        await interaction.followup.send(f"올바르지 않은 YouTube URL입니다: {exc}", ephemeral=True)
        return
    except (IpBlocked, RequestBlocked):
        await interaction.followup.send(
            (
                "YouTube가 이 봇 서버 IP의 자막 요청을 차단했습니다.\n"
                "클라우드 호스팅 IP이거나 요청이 많을 때 자주 발생합니다. "
                "나중에 다시 시도하거나, 다른 네트워크에서 봇을 실행하거나, "
                "youtube-transcript-api용 프록시를 설정하세요."
            ),
            ephemeral=True,
        )
        return
    except TranscriptsDisabled:
        await interaction.followup.send(
            "이 영상은 youtube-transcript-api에서 접근 가능한 공개 자막을 제공하지 않습니다.",
            ephemeral=True,
        )
        return
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"사용 가능한 수동 자막이 없습니다: {exc}", ephemeral=True)
        return
    except YouTubeTranscriptApiException as exc:
        logger.exception("YouTube 자막 조회에 실패했습니다.")
        await interaction.followup.send(
            f"YouTube 자막 조회에 실패했습니다: {type(exc).__name__}",
            ephemeral=True,
        )
        return
    except Exception as exc:
        logger.exception("가사 자막 테스트 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"자막 테스트에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"가사 출처: `{raw.source_type}` / 언어: `{raw.language_code or language_code}`\n"
            f"검토 필요: `{raw.needs_review}` / 오디오 fallback: `{audio_fallback}`\n"
            f"{_openai_status_text(translation_ko, pronunciation_ko, openai_error)}\n"
            f"리포트 저장 경로: `{report_path}`"
        ),
        file=discord.File(report_path),
        ephemeral=True,
    )


async def start_discord_bot() -> None:
    """토큰이 설정되어 있으면 Discord 봇을 시작하고, 없으면 비활성 상태로 둡니다."""
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN이 설정되어 있지 않아 Discord 봇을 비활성화합니다.")
        return

    await bot.start(settings.discord_bot_token)

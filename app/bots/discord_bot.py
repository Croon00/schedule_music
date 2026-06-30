from __future__ import annotations

from itertools import zip_longest
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from youtube_transcript_api._errors import YouTubeTranscriptApiException

from app.core.config import settings
from app.core.db import get_connection, init_db, row_to_dict
from app.integrations.google_calendar import (
    build_google_auth_url,
    google_connected,
    google_oauth_configured,
)
from app.integrations.youtube_context import (
    extract_lyrics_candidate,
    fetch_top_comment,
    fetch_video_description,
)
from app.lyrics_pipeline.clients import (
    OpenAiLyricsClient,
    OpenAiSpeechToTextClient,
    YouTubeTranscriptCaptionClient,
    YtDlpAudioDownloader,
)
from app.lyrics_pipeline.models import LyricsInput, LyricsSourceType, RawLyrics
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import extract_youtube_video_id
from app.namuwiki.ai_renderer import NamuWikiAiRenderError, render_song_article_from_template
from app.namuwiki.models import (
    NamuWikiLyricLine,
    NamuWikiSongArticleRequest,
    NamuWikiTemplateCreate,
    NamuWikiTemplateSongArticleRequest,
)
from app.namuwiki.template_store import (
    NamuWikiTemplateNotFoundError,
    get_template,
    list_templates,
    save_template,
)

logger = logging.getLogger(__name__)

LYRICS_SAMPLE_MAX_CHARS = 15000
LYRICS_SAMPLE_MAX_LINES = 15000
LYRICS_EXPORT_DIR = Path("exports")
NAMUWIKI_EXPORT_DIR = Path("exports") / "namuwiki"
NAMUWIKI_FIELD_MAX_CHARS = 500
LyricsSourceMode = Literal["description", "comment", "caption", "audio"]


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
        "## 원문",
        "",
        _caption_sample(raw.text),
    ]
    if translation_ko is not None:
        sections.extend(["", "## 한국어 번역", "", translation_ko])
    if pronunciation_ko is not None:
        sections.extend(["", "## 한글 발음", "", pronunciation_ko])
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


async def _fetch_context_lyrics_candidate(
    *,
    video_id: str,
    youtube_url: str,
    use_description: bool,
    use_comment: bool,
    language_code: str,
) -> RawLyrics | None:
    candidates = []
    if use_description:
        description = await fetch_video_description(video_id)
        if description:
            candidates.append((LyricsSourceType.YOUTUBE_DESCRIPTION, description))
    if use_comment:
        comment = await fetch_top_comment(video_id)
        if comment:
            candidates.append((LyricsSourceType.YOUTUBE_COMMENT, comment))

    for source_type, candidate in candidates:
        extracted = await extract_lyrics_candidate(candidate.text, candidate.source)
        if not extracted:
            continue
        excerpt, _reason = extracted
        return RawLyrics(
            text=excerpt,
            source_type=source_type,
            language_code=language_code,
            source_url=youtube_url,
            needs_review=True,
        )
    return None


def _lyrics_pipeline_for_source(
    *,
    language_code: str,
    audio_enabled: bool,
) -> LyricsPipeline:
    return LyricsPipeline(
        caption_client=YouTubeTranscriptCaptionClient(),
        ai_client=_NoopLyricsAiClient(),
        audio_downloader=YtDlpAudioDownloader() if audio_enabled else None,
        speech_to_text_client=(
            OpenAiSpeechToTextClient(language=language_code.strip() or "ja")
            if audio_enabled
            else None
        ),
    )


async def _collect_raw_lyrics_from_youtube(
    *,
    youtube_url: str,
    language_code: str,
    source_mode: LyricsSourceMode,
) -> RawLyrics:
    video_id = extract_youtube_video_id(youtube_url)
    normalized_language = language_code.strip() or "ja"
    pipeline = _lyrics_pipeline_for_source(
        language_code=normalized_language,
        audio_enabled=source_mode == "audio",
    )

    if source_mode == "description":
        raw = await _fetch_context_lyrics_candidate(
            video_id=video_id,
            youtube_url=youtube_url,
            use_description=True,
            use_comment=False,
            language_code=normalized_language,
        )
        if raw:
            return raw
        raise LyricsPipelineError("설명란에서 가사 후보를 찾지 못했습니다.")

    if source_mode == "comment":
        raw = await _fetch_context_lyrics_candidate(
            video_id=video_id,
            youtube_url=youtube_url,
            use_description=False,
            use_comment=True,
            language_code=normalized_language,
        )
        if raw:
            return raw
        raise LyricsPipelineError("상단 댓글에서 가사 후보를 찾지 못했습니다.")

    if source_mode == "caption":
        return await pipeline.get_raw_lyrics(
            LyricsInput(
                youtube_url=youtube_url,
                preferred_languages=(normalized_language, "ja", "en", "ko"),
                allow_audio_fallback=False,
            )
        )

    if source_mode == "audio":
        audio_path = await YtDlpAudioDownloader().download_audio(youtube_url)
        text = (await OpenAiSpeechToTextClient(language=normalized_language).transcribe(audio_path)).strip()
        if not text:
            raise LyricsPipelineError("오디오 전사 결과가 비어 있습니다.")
        return RawLyrics(
            text=text,
            source_type=LyricsSourceType.AUDIO_TRANSCRIPT,
            language_code=normalized_language,
            source_url=youtube_url,
            needs_review=True,
        )

    raise LyricsPipelineError("지원하지 않는 YouTube 가사 소스입니다.")


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


def _namuwiki_article_path(title: str, discord_user_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_") or "article"
    return NAMUWIKI_EXPORT_DIR / f"{safe_title}_{discord_user_id}_{timestamp}.txt"


def _template_text_from_inputs(
    template_text: str | None,
    template_file_text: str | None,
) -> str:
    text = (template_file_text or template_text or "").strip()
    if not text:
        raise ValueError("템플릿 본문 또는 템플릿 txt 파일이 필요합니다.")
    return text


def _split_nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _truncate_namuwiki_field(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:NAMUWIKI_FIELD_MAX_CHARS]


def _build_lyric_lines(
    original: str,
    pronunciation_ko: str,
    translation_ko: str,
) -> list[NamuWikiLyricLine]:
    lines = []
    for original_line, pronunciation_line, translation_line in zip_longest(
        _split_nonempty_lines(original),
        _split_nonempty_lines(pronunciation_ko),
        _split_nonempty_lines(translation_ko),
        fillvalue=None,
    ):
        lines.append(
            NamuWikiLyricLine(
                original=_truncate_namuwiki_field(original_line),
                pronunciation_ko=_truncate_namuwiki_field(pronunciation_line),
                translation_ko=_truncate_namuwiki_field(translation_line),
            )
        )
    return lines


async def _fetch_template_attachment_text(template_file: discord.Attachment | None) -> str | None:
    if template_file is None:
        return None
    raw = await template_file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("템플릿 파일은 UTF-8 txt 파일이어야 합니다.") from exc


async def _collect_raw_lyrics_for_namuwiki(
    *,
    youtube_url: str,
    language_code: str,
    source_mode: LyricsSourceMode,
) -> RawLyrics:
    return await _collect_raw_lyrics_from_youtube(
        youtube_url=youtube_url,
        language_code=language_code,
        source_mode=source_mode,
    )


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
        if settings.database_auto_init:
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
    name="lyrics_source_test",
    description="YouTube URL에서 설명란, 상단 댓글, 수동 자막, 오디오 전사 중 하나를 테스트합니다.",
)
@app_commands.describe(
    youtube_url="확인할 YouTube URL",
    source_mode="가사를 가져올 소스입니다. description, comment, caption, audio 중 하나만 사용합니다.",
    language_code="원문 언어 코드입니다. 예: ja, en, ko",
)
async def lyrics_source_test(
    interaction: discord.Interaction,
    youtube_url: str,
    source_mode: LyricsSourceMode = "caption",
    language_code: str = "ja",
) -> None:
    await interaction.response.defer(ephemeral=True)
    caption_client = YouTubeTranscriptCaptionClient()

    try:
        video_id = extract_youtube_video_id(youtube_url)
        try:
            tracks = await caption_client.list_tracks(video_id)
        except YouTubeTranscriptApiException:
            tracks = []

        raw = await _collect_raw_lyrics_from_youtube(
            youtube_url=youtube_url,
            language_code=language_code,
            source_mode=source_mode,
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
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"가사 후보를 찾지 못했습니다: {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("가사 소스 테스트 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"가사 소스 테스트에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"가사 출처: `{raw.source_type}` / 언어: `{raw.language_code or language_code}`\n"
            f"source_mode: `{source_mode}` / 검토 필요: `{raw.needs_review}`\n"
            f"{_openai_status_text(translation_ko, pronunciation_ko, openai_error)}\n"
            f"리포트 저장 경로: `{report_path}`"
        ),
        file=discord.File(report_path),
        ephemeral=True,
    )


@bot.tree.command(name="namuwiki_template_add", description="나무위키 문서 템플릿을 저장합니다.")
@app_commands.describe(
    template_id="나중에 선택할 템플릿 ID입니다. 예: hachi_song",
    name="템플릿 표시 이름입니다.",
    template_file="나무위키 예시 문서가 들어 있는 UTF-8 txt 파일입니다.",
    template_text="짧은 템플릿이면 직접 입력할 수 있습니다.",
    description="선택 설명입니다.",
)
async def namuwiki_template_add(
    interaction: discord.Interaction,
    template_id: str,
    name: str,
    template_file: discord.Attachment | None = None,
    template_text: str | None = None,
    description: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        template_file_text = await _fetch_template_attachment_text(template_file)
        template_example = _template_text_from_inputs(template_text, template_file_text)
        template = save_template(
            NamuWikiTemplateCreate(
                template_id=template_id.strip(),
                name=name.strip(),
                description=description,
                template_example=template_example,
            )
        )
    except Exception as exc:
        logger.exception("나무위키 템플릿 저장 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"템플릿 저장에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"나무위키 템플릿 저장 완료: `{template.template_id}`\n"
            f"이름: {template.name}\n"
            f"길이: {len(template.template_example)}자"
        ),
        ephemeral=True,
    )


@bot.tree.command(name="namuwiki_template_list", description="저장된 나무위키 템플릿 목록을 봅니다.")
async def namuwiki_template_list(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    templates = list_templates()
    if not templates:
        await interaction.followup.send("저장된 나무위키 템플릿이 없습니다.", ephemeral=True)
        return

    lines = []
    for template in templates[:25]:
        suffix = f" - {template.description}" if template.description else ""
        lines.append(f"`{template.template_id}`: {template.name}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="namuwiki_render", description="저장된 템플릿으로 나무위키 곡 문서를 만듭니다.")
@app_commands.describe(
    template_id="사용할 저장 템플릿 ID입니다.",
    title="곡 제목입니다.",
    artist="아티스트 이름입니다.",
    youtube_url="가사를 가져올 YouTube URL입니다.",
    release_date="선택 발매일입니다. 예: 2026. 06. 25.",
    album="선택 앨범/싱글명입니다.",
    language_code="원문 언어 코드입니다. 예: ja, en, ko",
    source_mode="가사를 가져올 소스입니다. description, comment, caption, audio 중 하나만 사용합니다.",
    extra_instruction="템플릿 적용 시 추가 지시입니다.",
)
async def namuwiki_render(
    interaction: discord.Interaction,
    template_id: str,
    title: str,
    artist: str,
    youtube_url: str,
    release_date: str | None = None,
    album: str | None = None,
    language_code: str = "ja",
    source_mode: LyricsSourceMode = "caption",
    extra_instruction: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.openai_api_key:
        await interaction.followup.send("OPENAI_API_KEY가 설정되어 있어야 합니다.", ephemeral=True)
        return

    try:
        template = get_template(template_id.strip())
        raw = await _collect_raw_lyrics_for_namuwiki(
            youtube_url=youtube_url,
            language_code=language_code,
            source_mode=source_mode,
        )

        ai_client = OpenAiLyricsClient()
        translation_ko, pronunciation_ko = await ai_client.transform_lyrics(
            lyrics=raw.text,
            artist=artist,
            title=title,
        )
        song = NamuWikiSongArticleRequest(
            title=title,
            artist=artist,
            release_date=release_date,
            album=album,
            youtube_url=youtube_url,
            lyrics=_build_lyric_lines(raw.text, pronunciation_ko, translation_ko),
        )
        article = await render_song_article_from_template(
            NamuWikiTemplateSongArticleRequest(
                template_example=template.template_example,
                song=song,
                extra_instruction=extra_instruction,
            )
        )

        output_path = _namuwiki_article_path(title, str(interaction.user.id))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(article, encoding="utf-8")
    except NamuWikiTemplateNotFoundError:
        await interaction.followup.send(f"템플릿 `{template_id}`를 찾지 못했습니다.", ephemeral=True)
        return
    except (ValueError, LyricsPipelineError, NamuWikiAiRenderError) as exc:
        await interaction.followup.send(f"나무위키 문서 생성에 실패했습니다: {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("나무위키 문서 생성 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"나무위키 문서 생성에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"나무위키 문서 생성 완료: `{title}`\n"
            f"템플릿: `{template.template_id}` / source_mode: `{source_mode}` / 가사 출처: `{raw.source_type}`\n"
            f"검토 필요: `{raw.needs_review}` / 저장 경로: `{output_path}`"
        ),
        file=discord.File(output_path),
        ephemeral=True,
    )


async def start_discord_bot() -> None:
    """토큰이 설정되어 있으면 Discord 봇을 시작하고, 없으면 비활성 상태로 둡니다."""
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN이 설정되어 있지 않아 Discord 봇을 비활성화합니다.")
        return

    await bot.start(settings.discord_bot_token)

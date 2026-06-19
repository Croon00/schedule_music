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
    """Discord ?낅젰媛믪뿉???욎そ @? 怨듬갚???쒓굅??X username留??④퉩?덈떎."""
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


def _openai_status_text(
    translation_ko: str | None,
    pronunciation_ko: str | None,
    error: str | None = None,
) -> str:
    if error:
        return f"OpenAI 誘몃━蹂닿린 蹂?? `?ㅽ뙣 ({error})`"
    if translation_ko is None and pronunciation_ko is None:
        return "OpenAI 誘몃━蹂닿린 蹂?? `嫄대꼫? (OPENAI_API_KEY 誘몄꽕??`"
    return "OpenAI 誘몃━蹂닿린 蹂?? `?꾨즺`"


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
    """Discord ?ъ슜??怨꾩젙??洹?띾맂 ?꾪떚?ㅽ듃? X 異쒖쿂瑜?DB???④퍡 ?깅줉?⑸땲??"""
    normalized_x_username = _normalize_x_username(x_username)
    if not normalized_x_username:
        raise ValueError("X ?ъ슜?먮챸? ?꾩닔?낅땲??")

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
    """?붿껌??Discord ?ъ슜?먭? ?뚯쑀???꾪떚?ㅽ듃留???젣?⑸땲??"""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM artists WHERE id = %s AND discord_user_id = %s",
            (artist_id, discord_user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def _list_artists(discord_user_id: str) -> list[dict]:
    """Discord ?ъ슜?먯뿉寃??깅줉???꾪떚?ㅽ듃? ???X username 紐⑸줉??議고쉶?⑸땲??"""
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
    """schedule_music ?꾩슜 Discord slash command 遊??대씪?댁뼵?몄엯?덈떎."""

    def __init__(self) -> None:
        """Discord client? slash command tree瑜?珥덇린?뷀빀?덈떎."""
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        """遊?濡쒓렇??吏곹썑 DB瑜?以鍮꾪븯怨?slash command瑜?Discord???숆린?뷀빀?덈떎."""
        init_db()
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Discord 紐낅졊?대? 湲몃뱶 %s???숆린?뷀뻽?듬땲??", settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("Discord 紐낅졊?대? ?꾩뿭?쇰줈 ?숆린?뷀뻽?듬땲??")


bot = ScheduleMusicBot()


@bot.tree.command(name="artist_add", description="?꾪떚?ㅽ듃? X 怨꾩젙???깅줉?⑸땲??")
@app_commands.describe(
    name="?꾪떚?ㅽ듃 ?대쫫",
    x_username="@ ?ы븿 ?щ?? 愿怨꾩뾾??X ?ъ슜?먮챸",
    display_name="?좏깮 ?쒖떆 ?대쫫",
    notes="?좏깮 硫붾え",
)
async def artist_add(
    interaction: discord.Interaction,
    name: str,
    x_username: str,
    display_name: str | None = None,
    notes: str | None = None,
) -> None:
    """Discord slash command濡??꾪떚?ㅽ듃? X 怨꾩젙???깅줉?⑸땲??"""
    await interaction.response.defer(ephemeral=True)
    try:
        artist = _create_artist(str(interaction.user.id), name, x_username, display_name, notes)
    except Exception as exc:
        logger.exception("?꾪떚?ㅽ듃 ?깅줉 紐낅졊 泥섎━???ㅽ뙣?덉뒿?덈떎.")
        await interaction.followup.send(f"?꾪떚?ㅽ듃 ?깅줉???ㅽ뙣?덉뒿?덈떎: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        f"?꾪떚?ㅽ듃 #{artist['id']} ?깅줉 ?꾨즺: {artist['name']} (@{_normalize_x_username(x_username)})",
        ephemeral=True,
    )


@bot.tree.command(name="artist_list", description="?깅줉???꾪떚?ㅽ듃 紐⑸줉??蹂댁뿬以띾땲??")
async def artist_list(interaction: discord.Interaction) -> None:
    """?꾩옱 Discord ?ъ슜?먭? ?깅줉???꾪떚?ㅽ듃 紐⑸줉??蹂댁뿬以띾땲??"""
    await interaction.response.defer(ephemeral=True)
    artists = _list_artists(str(interaction.user.id))
    if not artists:
        await interaction.followup.send("?꾩쭅 ?깅줉???꾪떚?ㅽ듃媛 ?놁뒿?덈떎.", ephemeral=True)
        return

    lines = []
    for artist in artists:
        display = artist["display_name"] or artist["name"]
        x_username = artist["x_username"]
        suffix = f" (@{x_username})" if x_username else ""
        lines.append(f"#{artist['id']} {display}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="artist_delete", description="ID濡??꾪떚?ㅽ듃瑜???젣?⑸땲??")
@app_commands.describe(artist_id="/artist_list???쒖떆???꾪떚?ㅽ듃 ID")
async def artist_delete(interaction: discord.Interaction, artist_id: int) -> None:
    """?꾩옱 Discord ?ъ슜?먯쓽 ?꾪떚?ㅽ듃瑜?ID 湲곗??쇰줈 ??젣?⑸땲??"""
    await interaction.response.defer(ephemeral=True)
    deleted = _delete_artist(str(interaction.user.id), artist_id)
    if deleted:
        await interaction.followup.send(f"?꾪떚?ㅽ듃 #{artist_id}瑜???젣?덉뒿?덈떎.", ephemeral=True)
    else:
        await interaction.followup.send(f"?꾪떚?ㅽ듃 #{artist_id}瑜?李얠? 紐삵뻽?듬땲??", ephemeral=True)


@bot.tree.command(name="google_connect", description="Google Calendar瑜??곌껐?⑸땲??")
async def google_connect(interaction: discord.Interaction) -> None:
    """?꾩옱 Discord ?ъ슜?먯뿉寃?Google Calendar OAuth ?곌껐 留곹겕瑜??덈궡?⑸땲??"""
    await interaction.response.defer(ephemeral=True)
    if google_connected(str(interaction.user.id)):
        await interaction.followup.send("Google Calendar媛 ?대? ?곌껐?섏뼱 ?덉뒿?덈떎.", ephemeral=True)
        return
    if not google_oauth_configured():
        await interaction.followup.send(
            "?쒕쾭??Google OAuth ?ㅼ젙???꾩쭅 ?놁뒿?덈떎.",
            ephemeral=True,
        )
        return

    auth_url = build_google_auth_url(str(interaction.user.id))
    await interaction.followup.send(
        f"?꾨옒 留곹겕?먯꽌 Google Calendar瑜??곌껐?섏꽭??\n{auth_url}",
        ephemeral=True,
    )


@bot.tree.command(
    name="lyrics_caption_test",
    description="YouTube URL???섎룞 ?먮쭑 異붿텧???뚯뒪?명빀?덈떎.",
)
@app_commands.describe(
    youtube_url="?뺤씤??YouTube URL",
    audio_fallback="?섎룞 ?먮쭑???놁쓣 ???덇???吏㏃? ?ㅻ뵒??fallback???ъ슜?⑸땲??",
    language_code="Whisper???꾨떖???먮Ц ?몄뼱 肄붾뱶?낅땲?? ?? ja, en, ko",
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
            logger.exception("媛??誘몃━蹂닿린 蹂?섏뿉 ?ㅽ뙣?덉뒿?덈떎.")
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
        await interaction.followup.send(f"?щ컮瑜댁? ?딆? YouTube URL?낅땲?? {exc}", ephemeral=True)
        return
    except (IpBlocked, RequestBlocked):
        await interaction.followup.send(
            (
                "YouTube媛 ??遊??쒕쾭 IP???먮쭑 ?붿껌??李⑤떒?덉뒿?덈떎.\n"
                "?대씪?곕뱶 ?몄뒪??IP?닿굅???붿껌??留롮쓣 ???먯＜ 諛쒖깮?⑸땲?? "
                "?섏쨷???ㅼ떆 ?쒕룄?섍굅?? ?ㅻⅨ ?ㅽ듃?뚰겕?먯꽌 遊뉗쓣 ?ㅽ뻾?섍굅?? "
                "youtube-transcript-api???꾨줉?쒕? ?ㅼ젙?섏꽭??"
            ),
            ephemeral=True,
        )
        return
    except TranscriptsDisabled:
        await interaction.followup.send(
            "???곸긽? youtube-transcript-api?먯꽌 ?묎렐 媛?ν븳 怨듦컻 ?먮쭑???쒓났?섏? ?딆뒿?덈떎.",
            ephemeral=True,
        )
        return
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"?ъ슜 媛?ν븳 ?섎룞 ?먮쭑???놁뒿?덈떎: {exc}", ephemeral=True)
        return
    except YouTubeTranscriptApiException as exc:
        logger.exception("YouTube ?먮쭑 議고쉶???ㅽ뙣?덉뒿?덈떎.")
        await interaction.followup.send(
            f"YouTube ?먮쭑 議고쉶???ㅽ뙣?덉뒿?덈떎: {type(exc).__name__}",
            ephemeral=True,
        )
        return
    except Exception as exc:
        logger.exception("媛???먮쭑 ?뚯뒪??紐낅졊 泥섎━???ㅽ뙣?덉뒿?덈떎.")
        await interaction.followup.send(f"?먮쭑 ?뚯뒪?몄뿉 ?ㅽ뙣?덉뒿?덈떎: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"媛??異쒖쿂: `{raw.source_type}` / ?몄뼱: `{raw.language_code or language_code}`\n"
            f"寃???꾩슂: `{raw.needs_review}` / ?ㅻ뵒??fallback: `{audio_fallback}`\n"
            f"{_openai_status_text(translation_ko, pronunciation_ko, openai_error)}\n"
            f"由ы룷?????寃쎈줈: `{report_path}`"
        ),
        file=discord.File(report_path),
        ephemeral=True,
    )


@bot.tree.command(
    name="lyrics_source_test",
    description="YouTube URL?먯꽌 ?먮쭑, ?ㅻ챸?, ?곷떒 ?볤?, ?ㅻ뵒??fallback???좏깮???뚯뒪?명빀?덈떎.",
)
@app_commands.describe(
    youtube_url="?뺤씤??YouTube URL",
    description_fallback="?섎룞 ?먮쭑???놁쑝硫??곸긽 ?ㅻ챸??먯꽌 媛???꾨낫瑜?李얠뒿?덈떎.",
    comment_fallback="?섎룞 ?먮쭑???놁쑝硫??곷떒 ?볤??먯꽌 媛???꾨낫瑜?李얠뒿?덈떎.",
    audio_fallback="?ㅻⅨ ?뚯뒪媛 ?ㅽ뙣?섎㈃ 吏㏃? ?ㅻ뵒??fallback???ъ슜?⑸땲??",
    language_code="?먮Ц ?몄뼱 肄붾뱶?낅땲?? ?? ja, en, ko",
)
async def lyrics_source_test(
    interaction: discord.Interaction,
    youtube_url: str,
    description_fallback: bool = False,
    comment_fallback: bool = False,
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
            tracks = []

        raw = None
        try:
            raw = await _fetch_context_lyrics_candidate(
                video_id=video_id,
                youtube_url=youtube_url,
                use_description=True,
                use_comment=False,
                language_code=language_code.strip() or "ja",
            )
        except Exception:
            logger.exception("YouTube 설명란에서 가사 후보를 찾는 데 실패했습니다.")

        if raw is None:
            try:
                raw = await pipeline.get_raw_lyrics(
                    LyricsInput(
                        youtube_url=youtube_url,
                        preferred_languages=(language_code.strip() or "ja", "ja", "en", "ko"),
                        allow_audio_fallback=False,
                    )
                )
            except Exception:
                logger.exception("수동 자막 조회에 실패했거나 사용할 수 있는 수동 자막이 없습니다.")

        if raw is None:
            try:
                raw = await _fetch_context_lyrics_candidate(
                    video_id=video_id,
                    youtube_url=youtube_url,
                    use_description=False,
                    use_comment=True,
                    language_code=language_code.strip() or "ja",
                )
            except Exception:
                logger.exception("YouTube 상단 댓글에서 가사 후보를 찾는 데 실패했습니다.")

        if raw is None and audio_fallback:
            raw = await pipeline.get_raw_lyrics(
                LyricsInput(
                    youtube_url=youtube_url,
                    preferred_languages=(language_code.strip() or "ja", "ja", "en", "ko"),
                    allow_audio_fallback=True,
                )
            )

        if raw is None:
            raise LyricsPipelineError("?좏깮???뚯뒪?먯꽌 媛???꾨낫瑜?李얠? 紐삵뻽?듬땲??")

        openai_error = None
        try:
            translation_ko, pronunciation_ko = await _transform_caption_preview(raw)
        except Exception as exc:
            logger.exception("媛??誘몃━蹂닿린 蹂?섏뿉 ?ㅽ뙣?덉뒿?덈떎.")
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
        await interaction.followup.send(f"?щ컮瑜댁? ?딆? YouTube URL?낅땲?? {exc}", ephemeral=True)
        return
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"媛???꾨낫瑜?李얠? 紐삵뻽?듬땲?? {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("媛???뚯뒪 ?뚯뒪??紐낅졊 泥섎━???ㅽ뙣?덉뒿?덈떎.")
        await interaction.followup.send(f"媛???뚯뒪 ?뚯뒪?몄뿉 ?ㅽ뙣?덉뒿?덈떎: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"媛??異쒖쿂: `{raw.source_type}` / ?몄뼱: `{raw.language_code or language_code}`\n"
            f"寃???꾩슂: `{raw.needs_review}`\n"
            f"{_openai_status_text(translation_ko, pronunciation_ko, openai_error)}\n"
            f"由ы룷?????寃쎈줈: `{report_path}`"
        ),
        file=discord.File(report_path),
        ephemeral=True,
    )


async def start_discord_bot() -> None:
    """?좏겙???ㅼ젙?섏뼱 ?덉쑝硫?Discord 遊뉗쓣 ?쒖옉?섍퀬, ?놁쑝硫?鍮꾪솢???곹깭濡??〓땲??"""
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN???ㅼ젙?섏뼱 ?덉? ?딆븘 Discord 遊뉗쓣 鍮꾪솢?깊솕?⑸땲??")
        return

    await bot.start(settings.discord_bot_token)

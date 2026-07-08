from __future__ import annotations

from collections.abc import Callable
import re

from app.namuwiki.models import NamuWikiSongArticleRequest
from app.namuwiki.renderer import (
    _collect_extra_credits,
    _extract_youtube_video_id,
    _render_name,
    _render_video,
)


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")


def has_placeholders(template: str) -> bool:
    return bool(PLACEHOLDER_PATTERN.search(template))


def render_song_article_from_placeholders(
    template: str,
    song: NamuWikiSongArticleRequest,
) -> str:
    values = _template_values(song)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if value is None:
            return ""
        return value() if callable(value) else value

    return PLACEHOLDER_PATTERN.sub(replace, template).rstrip() + "\n"


def _template_values(song: NamuWikiSongArticleRequest) -> dict[str, str | Callable[[], str]]:
    return {
        "title": song.title,
        "artist": song.artist,
        "release_date": song.release_date or "",
        "album": song.album or "",
        "album_type": song.album_type or "",
        "lyricist": lambda: _render_optional_name(song.lyricist, song.lyricist_ko),
        "composer": lambda: _render_optional_name(song.composer, song.composer_ko),
        "arranger": lambda: _render_optional_name(song.arranger, song.arranger_ko),
        "illustrator": lambda: _render_optional_name(song.illustrator, song.illustrator_ko),
        "video": lambda: _render_optional_name(song.video, song.video_ko),
        "producer": lambda: _render_optional_name(song.producer, song.producer_ko),
        "executive_producer": lambda: _render_optional_name(
            song.executive_producer,
            song.executive_producer_ko,
        ),
        "recording_director": lambda: _render_optional_name(
            song.recording_director,
            song.recording_director_ko,
        ),
        "recording_mixing": lambda: _render_optional_name(
            song.recording_mixing,
            song.recording_mixing_ko,
        ),
        "youtube_url": song.youtube_url or "",
        "youtube_id": lambda: _extract_youtube_video_id(song.youtube_url or "") or "",
        "video_section": lambda: _render_video(song),
        "cover_file": song.cover_file or "",
        "theme_song_for": song.theme_song_for or "",
        "intro": song.intro or "",
        "title_image_dark": song.title_image_dark or "",
        "title_image_light": song.title_image_light or "",
        "categories": lambda: "".join(
            f"[[분류:{category}]]" for category in song.categories if category.strip()
        ),
        "extra_credits": lambda: _render_plain_extra_credits(song),
        "lyrics": lambda: _render_plain_lyrics(song),
    }


def _render_optional_name(name: str | None, name_ko: str | None) -> str:
    if not name or not name.strip():
        return ""
    return _render_name(name.strip(), name_ko)


def _render_plain_extra_credits(song: NamuWikiSongArticleRequest) -> str:
    rows = []
    for credit in _collect_extra_credits(song):
        rows.append(f"|| '''{credit.role}''' ||||{_render_name(credit.name, credit.name_ko)} ||")
    return "\n".join(rows)


def _render_plain_lyrics(song: NamuWikiSongArticleRequest) -> str:
    rows: list[str] = []
    for line in song.lyrics:
        if line.is_blank:
            rows.append("")
            continue
        if line.original:
            rows.append(f"'''{line.original.strip()}'''")
        if line.pronunciation_ko:
            rows.append(f"{{{{{{#b1b1b1,#7f7f7f {line.pronunciation_ko.strip()}}}}}}}")
        if line.translation_ko:
            rows.append(f"{{{{{{#b1b1b1,#7f7f7f {line.translation_ko.strip()}}}}}}}")
    return "\n".join(rows)

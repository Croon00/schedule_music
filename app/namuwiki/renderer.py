from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.namuwiki.models import (
    NamuWikiCredit,
    NamuWikiExternalLink,
    NamuWikiLyricLine,
    NamuWikiSongArticleRequest,
)


TABLE_BORDER_COLOR = "#ffcc4d"
LYRIC_SUB_COLOR = "#b1b1b1,#7f7f7f"


def render_song_article(payload: NamuWikiSongArticleRequest) -> str:
    parts = [
        _render_categories(payload.categories),
        _render_discography_template(payload.discography_template),
        _render_infobox(payload),
        "[목차]\n[clearfix]",
        _render_overview(payload),
        _render_video(payload),
        _render_lyrics(payload),
    ]
    return "\n".join(part for part in parts if part).rstrip() + "\n"


def _render_categories(categories: list[str]) -> str:
    return "".join(f"[[분류:{category}]]" for category in categories if category.strip())


def _render_discography_template(template: str | None) -> str:
    if not template:
        return ""
    return f"[include(틀:{template})]"


def _render_infobox(payload: NamuWikiSongArticleRequest) -> str:
    rows = [
        "||<-3><tablewidth=400><tablealign=right>"
        f"<tablebordercolor={TABLE_BORDER_COLOR}><tablebgcolor=#fff,#2d2f34>"
        "<colbgcolor=#ddd,#010101><colcolor=#373a3c,#ddd> "
        f"'''{{{{{{+1 {payload.title}}}}}}}'''[br]  ||"
    ]
    if payload.cover_file:
        rows.append(
            "||<-3><bgcolor=#fff,#2d2f34><nopad> "
            f"[[파일:{payload.cover_file}|width=100%]] ||"
        )

    rows.append(
        "||<width=30%> '''가수''' ||||<colbgcolor=#f5f5f5,#2d2f34>"
        f"[[{payload.artist}]] ||"
    )
    if payload.album:
        album_text = payload.album
        if payload.album_type:
            album_text += f"{{{{{{-5 ({payload.album_type})}}}}}}"
        rows.append(f"|| '''음반''' ||||{album_text} ||")
    if payload.release_date:
        rows.append(f"|| '''발매일''' ||||{payload.release_date} ||")
    if payload.lyricist:
        rows.append(f"|| '''작사''' ||||{_render_name(payload.lyricist, payload.lyricist_ko)} ||")
    if payload.composer:
        rows.append(f"|| '''작곡''' ||||{_render_name(payload.composer, payload.composer_ko)} ||")
    if payload.arranger:
        rows.append(f"|| '''편곡''' ||||{_render_name(payload.arranger, payload.arranger_ko)} ||")
    extra_credits = _collect_extra_credits(payload)
    if extra_credits:
        rows.append(_render_extra_credits(extra_credits))
    if payload.external_links:
        rows.append("||<-2> '''외부 링크''' ||||||")
        rows.append(
            "||<-2><bgcolor=#ffffff,#191919> "
            + " | ".join(_render_external_link(link) for link in payload.external_links)
            + " ||||||"
        )
    return "\n".join(rows)


def _render_name(name: str, name_ko: str | None) -> str:
    if not name_ko:
        return name
    return f"{name} {{{{{{-5 | {name_ko}}}}}}}"


def _collect_extra_credits(payload: NamuWikiSongArticleRequest) -> list[NamuWikiCredit]:
    credits: list[NamuWikiCredit] = []
    fields = [
        ("일러스트", payload.illustrator, payload.illustrator_ko),
        ("영상", payload.video, payload.video_ko),
        ("프로듀서", payload.producer, payload.producer_ko),
        ("제작 총괄", payload.executive_producer, payload.executive_producer_ko),
        ("레코딩 총괄", payload.recording_director, payload.recording_director_ko),
        ("레코딩 & 믹싱", payload.recording_mixing, payload.recording_mixing_ko),
    ]
    for role, name, name_ko in fields:
        if name and name.strip():
            credits.append(NamuWikiCredit(role=role, name=name.strip(), name_ko=name_ko))
    credits.extend(payload.extra_credits)
    return credits


def _render_extra_credits(credits: list[NamuWikiCredit]) -> str:
    rows = [
        '||<-2> {{{#!wiki style="margin:0 -10px -5px; min-height:calc(1.5em + 5px)"',
        "{{{#!folding [ 기타 크레딧 ]",
        '{{{#!wiki style="margin:-5px -1px -11px"',
    ]
    for index, credit in enumerate(credits):
        prefix = "||<colbgcolor=#ddd,#010101><width=30%>" if index == 0 else "||"
        rows.append(
            f"{prefix} '''{credit.role}''' ||||<width=300>"
            f"{_render_name(credit.name, credit.name_ko)} ||"
        )
    rows.append("}}}}}}}}} ||")
    return "\n".join(rows)


def _render_external_link(link: NamuWikiExternalLink) -> str:
    icon = {
        "linkcore": "[[파일:링크코어 아이콘.svg|width=50&theme=light]][[파일:링크코어 아이콘D.svg|width=50&theme=dark]]",
        "youtube": "[[파일:유튜브 아이콘.svg|width=24]]",
        "spotify": "[[파일:스포티파이 아이콘.svg|width=24]]",
        "apple_music": "[[파일:Apple Music 아이콘.svg|width=24]]",
    }.get(link.type)
    label = icon or link.label or link.url
    return f"[[{link.url}|{label}]]"


def _render_overview(payload: NamuWikiSongArticleRequest) -> str:
    if payload.intro:
        overview = payload.intro.strip()
    else:
        date = f"{payload.release_date} 발매한 " if payload.release_date else ""
        album_type = f"{payload.album_type} " if payload.album_type else ""
        overview = f"{date}[[{payload.artist}]]의 {album_type}곡."
    if payload.theme_song_for:
        overview += f"\n\n{payload.theme_song_for} 테마곡."
    return f"== 개요 ==\n{overview}"


def _render_video(payload: NamuWikiSongArticleRequest) -> str:
    if not payload.youtube_url:
        return ""
    video_id = _extract_youtube_video_id(payload.youtube_url)
    if not video_id:
        return ""
    return (
        "== 영상 ==\n\n"
        f"||<tablealign=center><tablebordercolor={TABLE_BORDER_COLOR}><nopad> "
        f"[youtube({video_id})] ||\n"
        "||<bgcolor=#FFFFFF,#1F2023> '''MV''' ||"
    )


def _extract_youtube_video_id(url: str) -> str | None:
    if len(url) == 11 and "/" not in url and "?" not in url:
        return url
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/") or None
    if "youtube.com" in parsed.netloc:
        return parse_qs(parsed.query).get("v", [None])[0]
    return None


def _render_lyrics(payload: NamuWikiSongArticleRequest) -> str:
    rows = [
        "== 가사 ==",
        "",
        f"||<tablealign=center><tablebgcolor=#FFFFFF,#1F2023><tablebordercolor={TABLE_BORDER_COLOR}><tablewidth=600> ",
        "",
    ]
    title_images = _render_title_images(payload)
    if title_images:
        rows.extend(["", title_images, ""])

    for line in payload.lyrics:
        rows.extend(_render_lyric_line(line))
    rows.extend(["", "[br] ||"])
    return "\n".join(rows)


def _render_title_images(payload: NamuWikiSongArticleRequest) -> str:
    images = []
    if payload.title_image_dark:
        images.append(f"[[파일:{payload.title_image_dark}|width=200&theme=dark]]")
    if payload.title_image_light:
        images.append(f"[[파일:{payload.title_image_light}|width=200&theme=light]]")
    return "".join(images)


def _render_lyric_line(line: NamuWikiLyricLine) -> list[str]:
    if line.is_blank:
        return [""]

    rows: list[str] = []
    if line.original:
        rows.append(f"'''{line.original.strip()}'''")
    if line.pronunciation_ko:
        rows.append(f"{{{{{{{LYRIC_SUB_COLOR} {line.pronunciation_ko.strip()}}}}}}}")
    if line.translation_ko:
        rows.append(f"{{{{{{{LYRIC_SUB_COLOR} {line.translation_ko.strip()}}}}}}}")
    return rows

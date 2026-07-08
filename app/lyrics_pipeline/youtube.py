from __future__ import annotations

import re


YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|music/watch\?v=))"
    r"(?P<id>[A-Za-z0-9_-]{11})"
)


def extract_youtube_video_id(url: str) -> str:
    """일반적인 YouTube URL 형식에서 11자리 영상 ID를 반환합니다."""
    match = YOUTUBE_ID_RE.search(url)
    if match:
        return match.group("id")

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()

    raise ValueError("지원하지 않는 YouTube URL 또는 영상 ID입니다.")


def canonical_youtube_watch_url(url: str) -> str:
    video_id = extract_youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_caption_text(chunks: list[dict]) -> str:
    """자막 조각을 줄 단위의 간결한 가사 텍스트로 변환합니다."""
    lines: list[str] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        if not lines or text != lines[-1]:
            lines.append(text)
    return "\n".join(lines).strip()

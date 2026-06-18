from __future__ import annotations

import re


YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|music/watch\?v=))"
    r"(?P<id>[A-Za-z0-9_-]{11})"
)


def extract_youtube_video_id(url: str) -> str:
    """Return the 11-character YouTube video id from common URL formats."""
    match = YOUTUBE_ID_RE.search(url)
    if match:
        return match.group("id")

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()

    raise ValueError("Unsupported YouTube URL or video id.")


def normalize_caption_text(chunks: list[dict]) -> str:
    """Convert transcript chunks into compact line-oriented lyrics text."""
    lines: list[str] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        if not lines or text != lines[-1]:
            lines.append(text)
    return "\n".join(lines).strip()

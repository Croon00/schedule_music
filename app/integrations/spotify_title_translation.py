from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.db import get_connection


TITLE_TRANSLATION_SCHEMA = {
    "name": "spotify_track_title_translation",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "title_ko": {"type": "string"},
                    },
                    "required": ["id", "title_ko"],
                },
            }
        },
        "required": ["translations"],
    },
    "strict": True,
}
JAPANESE_TITLE_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff々〆ヶ]")


def _cached_titles(tracks: list[tuple[str, str]]) -> dict[str, str]:
    if not tracks:
        return {}
    ids = [track_id for track_id, _ in tracks]
    original_by_id = dict(tracks)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT spotify_track_id, original_title, title_ko
            FROM spotify_track_title_translations
            WHERE spotify_track_id = ANY(%s)
            """,
            (ids,),
        ).fetchall()
    return {
        row["spotify_track_id"]: row["title_ko"]
        for row in rows
        if row["original_title"] == original_by_id.get(row["spotify_track_id"])
    }


def _store_titles(translations: dict[str, str], original_by_id: dict[str, str]) -> None:
    if not translations:
        return
    with get_connection() as conn:
        for track_id, title_ko in translations.items():
            conn.execute(
                """
                INSERT INTO spotify_track_title_translations (
                    spotify_track_id, original_title, title_ko, model
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (spotify_track_id) DO UPDATE
                SET original_title = EXCLUDED.original_title,
                    title_ko = EXCLUDED.title_ko,
                    model = EXCLUDED.model,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (track_id, original_by_id[track_id], title_ko, settings.openai_model),
            )
        conn.commit()


async def resolve_korean_track_titles(tracks: list[tuple[str, str]]) -> dict[str, str]:
    """Return cached Korean translations and translate only unseen Japanese titles."""
    cached = _cached_titles(tracks)
    missing = [
        (track_id, title)
        for track_id, title in tracks
        if track_id not in cached and JAPANESE_TITLE_PATTERN.search(title)
    ]
    if not missing or not settings.openai_api_key:
        return cached

    translated = await translate_japanese_titles(missing)
    _store_titles(translated, dict(missing))
    return {**cached, **translated}


async def translate_japanese_titles(titles: list[tuple[str, str]]) -> dict[str, str]:
    """Translate Japanese titles without persisting them; callers own their cache."""
    candidates = [
        (item_id, title)
        for item_id, title in titles
        if JAPANESE_TITLE_PATTERN.search(title)
    ]
    if not candidates or not settings.openai_api_key:
        return {}
    translated: dict[str, str] = {}
    # Keep structured-output responses compact and reliable for large live
    # setlists/backfills.
    for start in range(0, len(candidates), 25):
        translated.update(await _translate_title_batch(candidates[start:start + 25]))
    return translated


async def translate_japanese_artist_names(names: list[tuple[str, str]]) -> dict[str, str]:
    """Return Korean-readable artist names, preserving established name forms."""
    candidates = [
        (item_id, name)
        for item_id, name in names
        if JAPANESE_TITLE_PATTERN.search(name)
    ]
    if not candidates or not settings.openai_api_key:
        return {}
    translated: dict[str, str] = {}
    for start in range(0, len(candidates), 25):
        batch = candidates[start:start + 25]
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write Japanese artist names in their common Korean spelling. "
                        "Return one result for every input item. If an artist is unfamiliar, "
                        "transcribe its Japanese pronunciation into Hangul. Do not translate meaning "
                        "or add explanations, punctuation, or parentheses."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        [{"id": item_id, "title": name} for item_id, name in batch],
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": TITLE_TRANSLATION_SCHEMA},
        )
        content = response.choices[0].message.content
        if not content:
            continue
        expected = dict(batch)
        translated.update({
            str(item["id"]): str(item["title_ko"]).strip()
            for item in json.loads(content).get("translations", [])
            if str(item.get("id") or "") in expected and str(item.get("title_ko") or "").strip()
        })
    return translated


async def _translate_title_batch(candidates: list[tuple[str, str]]) -> dict[str, str]:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate Japanese song titles into concise, natural Korean titles. "
                    "Do not add explanations, artists, punctuation, or parentheses. "
                    "Keep established English words as written."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    [{"id": item_id, "title": title} for item_id, title in candidates],
                    ensure_ascii=False,
                ),
            },
        ],
        response_format={"type": "json_schema", "json_schema": TITLE_TRANSLATION_SCHEMA},
    )
    content = response.choices[0].message.content
    if not content:
        return {}
    expected = dict(candidates)
    translated = {
        str(item["id"]): str(item["title_ko"]).strip()
        for item in json.loads(content).get("translations", [])
        if str(item.get("id") or "") in expected and str(item.get("title_ko") or "").strip()
    }
    return translated

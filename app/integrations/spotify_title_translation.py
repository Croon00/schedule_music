from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from app.core.config import settings
from app.repositories.spotify_title_translations import find_cached_titles, save_titles


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
    return find_cached_titles(tracks)


def _store_titles(translations: dict[str, str], original_by_id: dict[str, str]) -> None:
    save_titles(translations, original_by_id)


async def resolve_korean_track_titles(tracks: list[tuple[str, str]]) -> dict[str, str]:
    """캐시된 한국어 제목을 반환하고, 새 일본어 제목만 번역합니다."""
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
    """일본어 제목을 번역만 하며 저장 여부는 호출자가 결정합니다."""
    candidates = [
        (item_id, title)
        for item_id, title in titles
        if JAPANESE_TITLE_PATTERN.search(title)
    ]
    if not candidates or not settings.openai_api_key:
        return {}
    translated: dict[str, str] = {}
    # 대규모 라이브 세트리스트와 backfill에서도 구조화 응답을 작고 안정적으로
    # 유지하기 위해 한 번에 처리하는 항목 수를 제한합니다.
    for start in range(0, len(candidates), 25):
        translated.update(await _translate_title_batch(candidates[start:start + 25]))
    return translated


async def translate_japanese_artist_names(names: list[tuple[str, str]]) -> dict[str, str]:
    """널리 쓰이는 표기를 보존해 한국어로 읽을 수 있는 아티스트명을 반환합니다."""
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

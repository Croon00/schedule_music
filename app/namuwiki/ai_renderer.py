from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import settings
from app.namuwiki.models import NamuWikiTemplateSongArticleRequest


class NamuWikiAiRenderError(RuntimeError):
    pass


async def render_song_article_from_template(
    payload: NamuWikiTemplateSongArticleRequest,
) -> str:
    if not settings.openai_api_key:
        raise NamuWikiAiRenderError("OPENAI_API_KEY is required.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate NamuWiki markup for song articles. "
                    "Follow the user's template example closely: section order, table style, "
                    "folding blocks, icon link style, lyric formatting, spacing, and color syntax. "
                    "Replace the example song data with the provided song data. "
                    "Do not invent lyrics, credits, release dates, links, categories, or sources. "
                    "If a field is missing, leave the matching area blank or omit it in the same "
                    "style as the template would. Return only final NamuWiki markup."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Template example:\n"
                    f"{payload.template_example}\n\n"
                    "Song data as JSON:\n"
                    f"{payload.song.model_dump_json(indent=2)}\n\n"
                    "Extra instruction:\n"
                    f"{payload.extra_instruction or '(none)'}"
                ),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip() + "\n"

from app.core.config import settings
from app.core.db import get_connection


def find_cached_titles(tracks: list[tuple[str, str]]) -> dict[str, str]:
    """원문 제목이 일치하는 저장된 한국어 제목 번역만 조회한다."""
    if not tracks:
        return {}
    ids = [track_id for track_id, _ in tracks]
    originals = dict(tracks)
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT spotify_track_id, original_title, title_ko
            FROM spotify_track_title_translations WHERE spotify_track_id = ANY(%s)
        """, (ids,)).fetchall()
    return {row["spotify_track_id"]: row["title_ko"] for row in rows if row["original_title"] == originals.get(row["spotify_track_id"])}


def save_titles(translations: dict[str, str], originals: dict[str, str]) -> None:
    """OpenAI가 생성한 트랙 제목 번역을 모델 정보와 함께 저장한다."""
    if not translations:
        return
    with get_connection() as conn:
        for track_id, title_ko in translations.items():
            conn.execute("""
                INSERT INTO spotify_track_title_translations (spotify_track_id, original_title, title_ko, model)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (spotify_track_id) DO UPDATE SET original_title = EXCLUDED.original_title,
                    title_ko = EXCLUDED.title_ko, model = EXCLUDED.model, updated_at = CURRENT_TIMESTAMP
            """, (track_id, originals[track_id], title_ko, settings.openai_model))
        conn.commit()

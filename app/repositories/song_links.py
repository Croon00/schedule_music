from app.core.db import get_connection


def existing_spotify_track_ids(track_ids: list[str]) -> set[str]:
    """이미 songs 테이블에 연결된 Spotify 트랙 ID 집합을 조회한다."""
    if not track_ids:
        return set()
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT spotify_track_id FROM songs WHERE spotify_track_id = ANY(%s)", (track_ids,)).fetchall()
    return {str(row["spotify_track_id"]) for row in rows if row["spotify_track_id"]}


def save_spotify_youtube_link(*, track_id: str, title: str, artist_name: str, album_name: str | None, video_id: str, youtube_url: str, lyricist: str | None, composer: str | None, arranger: str | None) -> None:
    """검증된 Spotify–YouTube 연결과 크레딧을 저장하거나 갱신한다."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO songs (discord_user_id, original_title, artist_name, album_name, youtube_url,
                youtube_video_id, spotify_track_id, lyricist, composer, arranger)
            VALUES ('web', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_user_id, youtube_video_id) DO UPDATE SET
                original_title = EXCLUDED.original_title, artist_name = EXCLUDED.artist_name,
                album_name = EXCLUDED.album_name, spotify_track_id = EXCLUDED.spotify_track_id,
                lyricist = EXCLUDED.lyricist, composer = EXCLUDED.composer,
                arranger = EXCLUDED.arranger, updated_at = CURRENT_TIMESTAMP
        """, (title, artist_name, album_name, youtube_url, video_id, track_id, lyricist, composer, arranger))
        conn.commit()

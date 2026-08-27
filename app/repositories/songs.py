"""곡·가사 조회와 저장을 담당하는 Repository다."""

from typing import Any

from psycopg import Connection

from app.core.db import row_to_dict


class SongRepository:
    """`songs`와 `song_lyrics` 테이블 접근을 한곳에 모은다."""

    def __init__(self, connection: Connection):
        """요청 단위 PostgreSQL 연결을 보관한다."""
        self.connection = connection

    def get_artist_name(self, artist_id: int) -> str | None:
        """곡 생성에 필요한 등록 아티스트 표시명을 조회한다."""
        row = self.connection.execute("SELECT name, display_name FROM artists WHERE id = %s", (artist_id,)).fetchone()
        return (row["display_name"] or row["name"]) if row else None

    def list_lyrics_by_spotify_track_ids(self, track_ids: list[str]) -> list[dict[str, Any]]:
        """Spotify 트랙 ID 목록에 연결된 저장 곡을 조회한다."""
        return [row_to_dict(row) for row in self.connection.execute("""
            SELECT s.id AS song_id, s.spotify_track_id, s.youtube_url, s.lyricist, s.composer, s.arranger,
                EXISTS (SELECT 1 FROM song_lyrics l WHERE l.song_id = s.id) AS has_lyrics
            FROM songs s WHERE s.spotify_track_id = ANY(%s) ORDER BY s.updated_at DESC
            """, (track_ids,)).fetchall()]

    def upsert_spotify_youtube_link(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Spotify 트랙과 사용자가 고른 YouTube 영상을 연결한다."""
        existing = self.connection.execute("""SELECT s.id, EXISTS (SELECT 1 FROM song_lyrics l WHERE l.song_id = s.id) AS has_lyrics
            FROM songs s WHERE s.spotify_track_id = %s ORDER BY s.updated_at DESC LIMIT 1""", (values["spotify_track_id"],)).fetchone()
        parameters = (values["title"], values["artist_name"], values["album_name"], values["youtube_url"], values["youtube_video_id"], values["lyricist"], values["composer"], values["arranger"])
        if existing:
            row = self.connection.execute("""UPDATE songs SET original_title=%s, artist_name=%s, album_name=%s, youtube_url=%s,
                youtube_video_id=%s, lyricist=%s, composer=%s, arranger=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
                RETURNING id, spotify_track_id, youtube_url, lyricist, composer, arranger""", (*parameters, existing["id"])).fetchone()
        else:
            row = self.connection.execute("""INSERT INTO songs (discord_user_id, original_title, artist_name, album_name, youtube_url,
                youtube_video_id, spotify_track_id, lyricist, composer, arranger) VALUES ('web', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, spotify_track_id, youtube_url, lyricist, composer, arranger""", (*parameters[:5], values["spotify_track_id"], *parameters[5:])).fetchone()
        self.connection.commit()
        return row_to_dict(row), bool(existing and existing["has_lyrics"])

    def update_credits(self, song_id: int, values: dict[str, str | None]) -> dict[str, Any] | None:
        """수동 입력한 작사·작곡·편곡 정보를 저장한다."""
        row = self.connection.execute("""UPDATE songs SET lyricist=%s, composer=%s, arranger=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s
            RETURNING id, spotify_track_id, youtube_url, lyricist, composer, arranger,
            EXISTS (SELECT 1 FROM song_lyrics l WHERE l.song_id = songs.id) AS has_lyrics""", (values["lyricist"], values["composer"], values["arranger"], song_id)).fetchone()
        self.connection.commit()
        return row_to_dict(row)

    def get_lyrics(self, song_id: int) -> dict[str, Any] | None:
        """한 곡의 원문 가사·번역·발음 데이터를 조회한다."""
        row = self.connection.execute("""SELECT s.id AS song_id, s.original_title, t.title_ko, s.artist_name, s.album_name, s.youtube_url,
            l.original_lyrics, l.translation_ko, l.pronunciation_ko, l.lyrics_source_type, l.lyrics_source_url, l.needs_review
            FROM songs s JOIN song_lyrics l ON l.song_id=s.id LEFT JOIN spotify_track_title_translations t ON t.spotify_track_id=s.spotify_track_id
            AND t.original_title=s.original_title WHERE s.id=%s""", (song_id,)).fetchone()
        return row_to_dict(row)

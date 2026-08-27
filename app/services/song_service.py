"""곡·가사 API의 유스케이스를 담당한다."""

import httpx
from fastapi import HTTPException

from app.core.models import SongCreditsUpdate, SongLyricsDetail, SongLyricsSummary, SpotifyTrackYouTubeLinkCreate, WebSongCreate
from app.integrations.youtube_context import fetch_youtube_music_credits
from app.lyrics_pipeline.service import LyricsPipelineError
from app.lyrics_pipeline.song_service import save_song_from_youtube
from app.lyrics_pipeline.youtube import extract_youtube_video_id
from app.repositories.songs import SongRepository


class SongService:
    """곡 Repository와 외부 YouTube/가사 기능을 조합한다."""

    def __init__(self, repository: SongRepository):
        """요청 단위 곡 Repository를 주입받는다."""
        self.repository = repository

    async def create_from_youtube(self, payload: WebSongCreate) -> dict:
        """등록 아티스트의 YouTube 영상에서 가사를 생성한다."""
        artist_name = self.repository.get_artist_name(payload.artist_id)
        if artist_name is None:
            raise HTTPException(status_code=404, detail="아티스트를 찾을 수 없습니다.")
        try:
            return await save_song_from_youtube(artist=artist_name, title=payload.title.strip(), youtube_url=payload.youtube_url.strip(), source_mode=payload.source_mode, language_code=payload.language_code)
        except (ValueError, LyricsPipelineError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def list_by_spotify_tracks(self, ids: list[str]) -> list[SongLyricsSummary]:
        """요청한 Spotify 트랙의 가사 저장 상태를 반환한다."""
        rows = self.repository.list_lyrics_by_spotify_track_ids(list(dict.fromkeys(track_id for track_id in ids if track_id.strip()))) if ids else []
        results: dict[str, SongLyricsSummary] = {}
        for row in rows:
            results.setdefault(row["spotify_track_id"], SongLyricsSummary(**row))
        return list(results.values())

    async def link_spotify_track_to_youtube(self, payload: SpotifyTrackYouTubeLinkCreate) -> SongLyricsSummary:
        """Spotify 트랙에 선택한 YouTube 영상과 영상 설명의 크레딧을 저장한다."""
        try:
            video_id = extract_youtube_video_id(payload.youtube_url.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="올바른 YouTube 영상 URL을 입력해주세요.") from exc
        try:
            credits = await fetch_youtube_music_credits(video_id)
        except (RuntimeError, httpx.HTTPError):
            credits = None
        row, has_lyrics = self.repository.upsert_spotify_youtube_link({**payload.model_dump(), "youtube_url": payload.youtube_url.strip(), "youtube_video_id": video_id, "lyricist": credits.lyricist if credits else None, "composer": credits.composer if credits else None, "arranger": credits.arranger if credits else None})
        return SongLyricsSummary(**row, has_lyrics=has_lyrics)

    def update_credits(self, song_id: int, payload: SongCreditsUpdate) -> SongLyricsSummary:
        """수동 크레딧을 갱신한다."""
        row = self.repository.update_credits(song_id, payload.model_dump())
        if row is None:
            raise HTTPException(status_code=404, detail="곡을 찾을 수 없습니다.")
        if not row["spotify_track_id"]:
            raise HTTPException(status_code=409, detail="Spotify 트랙에 연결되지 않은 곡입니다.")
        return SongLyricsSummary(**row)

    def get_lyrics(self, song_id: int) -> SongLyricsDetail:
        """저장된 가사 상세 정보를 반환한다."""
        row = self.repository.get_lyrics(song_id)
        if row is None:
            raise HTTPException(status_code=404, detail="저장된 가사를 찾을 수 없습니다.")
        return SongLyricsDetail(**row)

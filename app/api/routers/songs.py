"""곡·가사 API 라우터다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_song_service
from app.core.models import SongCreditsUpdate, SongLyricsDetail, SongLyricsSummary, SpotifyTrackYouTubeLinkCreate, WebSongCreate, WebSongCreated
from app.core.security import require_api_key
from app.services.song_service import SongService

router = APIRouter(tags=["songs"], dependencies=[Depends(require_api_key)])
Service = Annotated[SongService, Depends(get_song_service)]


@router.post("/songs/from-youtube", response_model=WebSongCreated, status_code=status.HTTP_201_CREATED)
async def create_song_from_youtube(payload: WebSongCreate, service: Service) -> dict:
    """YouTube 영상에서 가사를 생성해 저장한다."""
    return await service.create_from_youtube(payload)


@router.get("/songs/lyrics/by-spotify-tracks", response_model=list[SongLyricsSummary])
def list_song_lyrics_by_spotify_tracks(service: Service, ids: list[str] = Query(default=[])) -> list[SongLyricsSummary]:
    """Spotify 트랙별 가사 저장 상태를 조회한다."""
    return service.list_by_spotify_tracks(ids)


@router.post("/songs/spotify-track-youtube", response_model=SongLyricsSummary)
async def link_spotify_track_to_youtube(payload: SpotifyTrackYouTubeLinkCreate, service: Service) -> SongLyricsSummary:
    """Spotify 트랙과 YouTube 영상을 연결한다."""
    return await service.link_spotify_track_to_youtube(payload)


@router.patch("/songs/{song_id}/credits", response_model=SongLyricsSummary)
def update_song_credits(song_id: int, payload: SongCreditsUpdate, service: Service) -> SongLyricsSummary:
    """곡의 수동 크레딧을 수정한다."""
    return service.update_credits(song_id, payload)


@router.get("/songs/{song_id}/lyrics", response_model=SongLyricsDetail)
def get_song_lyrics(song_id: int, service: Service) -> SongLyricsDetail:
    """곡 가사의 상세 내용을 반환한다."""
    return service.get_lyrics(song_id)

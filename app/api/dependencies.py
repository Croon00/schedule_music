from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.api.database_dependencies import get_db_connection
from app.repositories.songs import SongRepository
from app.services.artist_service import ArtistService
from app.services.song_service import SongService
from app.services.youtube_service import YouTubeService
from psycopg import Connection


def get_artist_service(session: Annotated[Session, Depends(get_session)]) -> ArtistService:
    """요청 단위 DB 세션으로 아티스트 유스케이스 서비스를 생성한다."""
    return ArtistService(session)


def get_song_repository(connection: Annotated[Connection, Depends(get_db_connection)]) -> SongRepository:
    """요청 DB 연결을 사용하는 곡 Repository를 생성한다."""
    return SongRepository(connection)


def get_song_service(repository: Annotated[SongRepository, Depends(get_song_repository)]) -> SongService:
    """곡 API에 필요한 유스케이스 서비스를 생성한다."""
    return SongService(repository)


def get_youtube_service() -> YouTubeService:
    """YouTube 외부 연동을 사용하는 서비스를 생성한다."""
    return YouTubeService()

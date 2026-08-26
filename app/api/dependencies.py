from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.artist_service import ArtistService


def get_artist_service(session: Annotated[Session, Depends(get_session)]) -> ArtistService:
    """요청 단위 DB 세션으로 아티스트 유스케이스 서비스를 생성한다."""
    return ArtistService(session)

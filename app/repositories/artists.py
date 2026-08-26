from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session, selectinload

from app.db.models import ArtistModel
from app.repositories.errors import NotFoundError


class ArtistRepository:
    """아티스트 aggregate의 생성·조회·수정·삭제 SQL을 담당한다."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, values: dict) -> ArtistModel:
        artist = ArtistModel(**values)
        self.session.add(artist)
        self.session.flush()
        return artist

    def list(self) -> list[ArtistModel]:
        statement: Select = select(ArtistModel).options(selectinload(ArtistModel.sources)).order_by(ArtistModel.name)
        return list(self.session.scalars(statement))

    def get(self, artist_id: int) -> ArtistModel:
        statement: Select = select(ArtistModel).options(selectinload(ArtistModel.sources)).where(ArtistModel.id == artist_id)
        artist = self.session.scalar(statement)
        if artist is None:
            raise NotFoundError("Artist not found.")
        return artist

    def require(self, artist_id: int) -> ArtistModel:
        artist = self.session.get(ArtistModel, artist_id)
        if artist is None:
            raise NotFoundError("Artist not found.")
        return artist

    def update(self, artist_id: int, values: dict) -> ArtistModel:
        artist = self.get(artist_id)
        for field, value in values.items():
            setattr(artist, field, value)
        self.session.flush()
        return artist

    def delete(self, artist_id: int) -> None:
        self.session.delete(self.require(artist_id))
        self.session.flush()

    def representative_youtube_url(self, artist: ArtistModel) -> str | None:
        """아티스트 화면에 표시할 가장 최근 YouTube 라이브 URL을 조회한다."""
        value = self.session.execute(text("""
            SELECT y.youtube_url FROM youtube_live_archives y
            LEFT JOIN artist_sources s ON s.id = y.source_id
            WHERE s.artist_id = :artist_id
               OR (s.id IS NULL AND LOWER(COALESCE(y.performer_name, '')) = LOWER(:artist_name))
            ORDER BY COALESCE(y.broadcast_at, y.published_at) DESC NULLS LAST, y.id DESC LIMIT 1
        """), {"artist_id": artist.id, "artist_name": artist.name}).scalar_one_or_none()
        return str(value) if value else None

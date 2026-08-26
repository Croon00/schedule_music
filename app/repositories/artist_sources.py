from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ArtistSourceModel
from app.repositories.errors import ConflictError, NotFoundError


class ArtistSourceRepository:
    """아티스트의 공식 계정·사이트 source 저장소를 담당한다."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, artist_id: int, values: dict) -> ArtistSourceModel:
        source = ArtistSourceModel(artist_id=artist_id, **values)
        self.session.add(source)
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("Source already exists.") from exc
        return source

    def list_for_artist(self, artist_id: int) -> list[ArtistSourceModel]:
        return list(self.session.scalars(select(ArtistSourceModel).where(ArtistSourceModel.artist_id == artist_id).order_by(ArtistSourceModel.source_type, ArtistSourceModel.value)))

    def delete_for_artist(self, artist_id: int, source_id: int) -> None:
        source = self.session.scalar(select(ArtistSourceModel).where(ArtistSourceModel.id == source_id, ArtistSourceModel.artist_id == artist_id))
        if source is None:
            raise NotFoundError("Source not found.")
        self.session.delete(source)
        self.session.flush()

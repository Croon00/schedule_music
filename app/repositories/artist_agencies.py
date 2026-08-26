from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ArtistAgencyModel
from app.repositories.errors import ConflictError


class ArtistAgencyRepository:
    """아티스트 소속사 목록의 조회와 생성 SQL을 담당한다."""
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[ArtistAgencyModel]:
        return list(self.session.scalars(select(ArtistAgencyModel).order_by(ArtistAgencyModel.name)))

    def create(self, name: str) -> ArtistAgencyModel:
        agency = ArtistAgencyModel(name=name)
        self.session.add(agency)
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("Agency already exists.") from exc
        return agency

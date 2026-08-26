from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM mappings.

    Schema creation remains in ``app.core.db.init_db`` during the migration so
    existing Railway databases are never altered implicitly by application
    imports.
    """


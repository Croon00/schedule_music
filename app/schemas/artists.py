"""Artist-domain Pydantic schemas.

The classes are re-exported during the compatibility migration; canonical API
code imports them from this package, while older worker code can keep using
``app.core.models`` until it is migrated.
"""

from app.core.models import (
    Artist,
    ArtistAgency,
    ArtistAgencyCreate,
    ArtistCreate,
    ArtistUpdate,
    ArtistWithSources,
    EventCandidate,
    EventCandidateCreate,
    Source,
    SourceCreate,
)

__all__ = [
    "Artist", "ArtistAgency", "ArtistAgencyCreate", "ArtistCreate", "ArtistUpdate",
    "ArtistWithSources", "EventCandidate", "EventCandidateCreate", "Source", "SourceCreate",
]

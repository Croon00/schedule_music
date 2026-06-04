from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg import Connection, errors

from app.core.config import settings
from app.core.db import get_connection, init_db, row_to_dict
from app.core.models import (
    Artist,
    ArtistCreate,
    ArtistUpdate,
    ArtistWithSources,
    EventCandidate,
    EventCandidateCreate,
    Source,
    SourceCreate,
)
from app.integrations.google_calendar import (
    build_google_auth_url,
    exchange_code_for_tokens,
    google_oauth_configured,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/google/start")
def start_google_auth(discord_user_id: str) -> RedirectResponse:
    if not google_oauth_configured():
        raise HTTPException(status_code=500, detail="Google OAuth is not configured.")
    return RedirectResponse(build_google_auth_url(discord_user_id))


@app.get("/auth/google/callback", response_class=HTMLResponse)
async def google_auth_callback(code: str, state: str) -> str:
    await exchange_code_for_tokens(code, state)
    return """
    <html>
      <body>
        <h1>Google Calendar connected</h1>
        <p>You can close this page and return to Discord.</p>
      </body>
    </html>
    """


@app.post("/artists", response_model=ArtistWithSources, status_code=status.HTTP_201_CREATED)
def create_artist(payload: ArtistCreate) -> dict:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artists (name, display_name, notes)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (payload.name, payload.display_name, payload.notes),
        )
        artist_id = cursor.fetchone()["id"]

        if payload.x_username:
            conn.execute(
                """
                INSERT INTO artist_sources (artist_id, source_type, label, value)
                VALUES (%s, 'x', 'X account', %s)
                """,
                (artist_id, payload.x_username),
            )

        conn.commit()
        return _get_artist_with_sources(conn, artist_id)


@app.get("/artists", response_model=list[ArtistWithSources])
def list_artists() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM artists ORDER BY name").fetchall()
        return [_get_artist_with_sources(conn, row["id"]) for row in rows]


@app.get("/artists/{artist_id}", response_model=ArtistWithSources)
def get_artist(artist_id: int) -> dict:
    with get_connection() as conn:
        return _get_artist_with_sources(conn, artist_id)


@app.patch("/artists/{artist_id}", response_model=Artist)
def update_artist(artist_id: int, payload: ArtistUpdate) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    assignments = ", ".join(f"{field} = %s" for field in fields)
    values = list(fields.values())

    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        conn.execute(
            f"""
            UPDATE artists
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            [*values, artist_id],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM artists WHERE id = %s", (artist_id,)).fetchone()
        return row_to_dict(row)


@app.delete("/artists/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artist(artist_id: int) -> Response:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        conn.execute("DELETE FROM artists WHERE id = %s", (artist_id,))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/artists/{artist_id}/sources",
    response_model=Source,
    status_code=status.HTTP_201_CREATED,
)
def add_artist_source(artist_id: int, payload: SourceCreate) -> dict:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        try:
            cursor = conn.execute(
                """
                INSERT INTO artist_sources (artist_id, source_type, label, value, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    artist_id,
                    payload.source_type,
                    payload.label,
                    payload.value,
                    payload.is_active,
                ),
            )
            source_id = cursor.fetchone()["id"]
            conn.commit()
        except errors.UniqueViolation as exc:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Source already exists.") from exc

        row = conn.execute(
            "SELECT * FROM artist_sources WHERE id = %s",
            (source_id,),
        ).fetchone()
        return _source_row_to_dict(row)


@app.get("/artists/{artist_id}/sources", response_model=list[Source])
def list_artist_sources(artist_id: int) -> list[dict]:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        rows = conn.execute(
            """
            SELECT * FROM artist_sources
            WHERE artist_id = %s
            ORDER BY source_type, value
            """,
            (artist_id,),
        ).fetchall()
        return [_source_row_to_dict(row) for row in rows]


@app.delete("/artists/{artist_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artist_source(artist_id: int, source_id: int) -> Response:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        cursor = conn.execute(
            "DELETE FROM artist_sources WHERE id = %s AND artist_id = %s",
            (source_id, artist_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Source not found.")
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/event-candidates", response_model=EventCandidate, status_code=status.HTTP_201_CREATED)
def create_event_candidate(payload: EventCandidateCreate) -> dict:
    data = payload.model_dump()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_candidates (
                artist_id, source_id, title, starts_at, venue, ticket_opens_at,
                ticket_url, price_text, source_url, raw_text, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["artist_id"],
                data["source_id"],
                data["title"],
                data["starts_at"],
                data["venue"],
                data["ticket_opens_at"],
                data["ticket_url"],
                data["price_text"],
                data["source_url"],
                data["raw_text"],
                data["status"],
            ),
        )
        event_candidate_id = cursor.fetchone()["id"]
        conn.commit()
        row = conn.execute(
            "SELECT * FROM event_candidates WHERE id = %s",
            (event_candidate_id,),
        ).fetchone()
        return row_to_dict(row)


@app.get("/event-candidates", response_model=list[EventCandidate])
def list_event_candidates(status_filter: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if status_filter:
            rows = conn.execute(
                """
                SELECT * FROM event_candidates
                WHERE status = %s
                ORDER BY created_at DESC
                """,
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM event_candidates ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_dict(row) for row in rows]


def _ensure_artist_exists(conn: Connection, artist_id: int) -> None:
    row = conn.execute("SELECT id FROM artists WHERE id = %s", (artist_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Artist not found.")


def _get_artist_with_sources(conn: Connection, artist_id: int) -> dict:
    artist = row_to_dict(
        conn.execute("SELECT * FROM artists WHERE id = %s", (artist_id,)).fetchone()
    )
    if artist is None:
        raise HTTPException(status_code=404, detail="Artist not found.")

    sources = conn.execute(
        """
        SELECT * FROM artist_sources
        WHERE artist_id = %s
        ORDER BY source_type, value
        """,
        (artist_id,),
    ).fetchall()
    artist["sources"] = [_source_row_to_dict(row) for row in sources]
    return artist


def _source_row_to_dict(row: dict | None) -> dict:
    source = row_to_dict(row)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source

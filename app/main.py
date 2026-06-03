from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status

from app.config import settings
from app.db import get_connection, init_db, row_to_dict
from app.models import (
    Artist,
    ArtistCreate,
    ArtistUpdate,
    ArtistWithSources,
    EventCandidate,
    EventCandidateCreate,
    Source,
    SourceCreate,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # FastAPI 앱이 시작될 때 SQLite 테이블을 준비합니다.
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


# 서버가 정상적으로 실행 중인지 확인하는 헬스 체크 API입니다.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 아티스트를 새로 등록하고, X 계정이 있으면 출처 정보도 함께 저장합니다.
@app.post("/artists", response_model=ArtistWithSources, status_code=status.HTTP_201_CREATED)
def create_artist(payload: ArtistCreate) -> dict:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artists (name, display_name, notes)
            VALUES (?, ?, ?)
            """,
            (payload.name, payload.display_name, payload.notes),
        )
        artist_id = cursor.lastrowid

        if payload.x_username:
            conn.execute(
                """
                INSERT INTO artist_sources (artist_id, source_type, label, value)
                VALUES (?, 'x', 'X account', ?)
                """,
                (artist_id, payload.x_username),
            )

        conn.commit()
        return _get_artist_with_sources(conn, artist_id)


# 등록된 모든 아티스트와 각 아티스트의 출처 목록을 조회합니다.
@app.get("/artists", response_model=list[ArtistWithSources])
def list_artists() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM artists ORDER BY name").fetchall()
        return [_get_artist_with_sources(conn, row["id"]) for row in rows]


# 특정 아티스트 한 명과 연결된 출처 목록을 조회합니다.
@app.get("/artists/{artist_id}", response_model=ArtistWithSources)
def get_artist(artist_id: int) -> dict:
    with get_connection() as conn:
        return _get_artist_with_sources(conn, artist_id)


# 아티스트 이름, 표시 이름, 메모를 부분 수정합니다.
@app.patch("/artists/{artist_id}", response_model=Artist)
def update_artist(artist_id: int, payload: ArtistUpdate) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = list(fields.values())

    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        conn.execute(
            f"""
            UPDATE artists
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [*values, artist_id],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        return row_to_dict(row)


# 아티스트를 삭제합니다. 연결된 출처는 DB 외래키 설정에 따라 함께 정리됩니다.
@app.delete("/artists/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artist(artist_id: int) -> Response:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        conn.execute("DELETE FROM artists WHERE id = ?", (artist_id,))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 기존 아티스트에 X, 공식 사이트, 티켓 사이트 같은 추가 출처를 등록합니다.
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
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artist_id,
                    payload.source_type,
                    payload.label,
                    payload.value,
                    int(payload.is_active),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Source already exists.") from exc

        row = conn.execute(
            "SELECT * FROM artist_sources WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _source_row_to_dict(row)


# 특정 아티스트에 등록된 출처 목록을 조회합니다.
@app.get("/artists/{artist_id}/sources", response_model=list[Source])
def list_artist_sources(artist_id: int) -> list[dict]:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        rows = conn.execute(
            """
            SELECT * FROM artist_sources
            WHERE artist_id = ?
            ORDER BY source_type, value
            """,
            (artist_id,),
        ).fetchall()
        return [_source_row_to_dict(row) for row in rows]


# 특정 아티스트에 연결된 출처 하나를 삭제합니다.
@app.delete("/artists/{artist_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artist_source(artist_id: int, source_id: int) -> Response:
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        cursor = conn.execute(
            "DELETE FROM artist_sources WHERE id = ? AND artist_id = ?",
            (source_id, artist_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Source not found.")
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 수집 또는 파싱된 공연/티켓 일정 후보를 저장합니다.
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        conn.commit()
        row = conn.execute(
            "SELECT * FROM event_candidates WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return row_to_dict(row)


# 저장된 일정 후보 목록을 조회합니다. status_filter가 있으면 해당 상태만 반환합니다.
@app.get("/event-candidates", response_model=list[EventCandidate])
def list_event_candidates(status_filter: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if status_filter:
            rows = conn.execute(
                """
                SELECT * FROM event_candidates
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM event_candidates ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_dict(row) for row in rows]


# 아티스트 ID가 실제로 존재하는지 확인하고, 없으면 404 에러를 반환합니다.
def _ensure_artist_exists(conn: sqlite3.Connection, artist_id: int) -> None:
    row = conn.execute("SELECT id FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Artist not found.")


# 아티스트 기본 정보에 출처 목록을 붙여 API 응답 형태로 만듭니다.
def _get_artist_with_sources(conn: sqlite3.Connection, artist_id: int) -> dict:
    artist = row_to_dict(
        conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
    )
    if artist is None:
        raise HTTPException(status_code=404, detail="Artist not found.")

    sources = conn.execute(
        """
        SELECT * FROM artist_sources
        WHERE artist_id = ?
        ORDER BY source_type, value
        """,
        (artist_id,),
    ).fetchall()
    artist["sources"] = [_source_row_to_dict(row) for row in sources]
    return artist


# SQLite row를 출처 응답 dict로 변환하고, is_active를 bool 타입으로 맞춥니다.
def _source_row_to_dict(row: sqlite3.Row | None) -> dict:
    source = row_to_dict(row)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    source["is_active"] = bool(source["is_active"])
    return source

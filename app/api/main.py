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
from app.namuwiki.ai_renderer import NamuWikiAiRenderError, render_song_article_from_template
from app.namuwiki.models import (
    NamuWikiSavedTemplateSongArticleRequest,
    NamuWikiSongArticleRequest,
    NamuWikiSongArticleResponse,
    NamuWikiTemplateCreate,
    NamuWikiTemplateDetail,
    NamuWikiTemplateInfo,
    NamuWikiTemplateSongArticleRequest,
)
from app.namuwiki.renderer import render_song_article
from app.namuwiki.template_store import (
    NamuWikiTemplateNotFoundError,
    get_template,
    list_templates,
    save_template,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """FastAPI 시작 시 PostgreSQL 스키마를 준비합니다."""
    if settings.database_url and settings.database_auto_init:
        init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """배포된 API 서버가 살아 있는지 확인하는 헬스 체크입니다."""
    return {"status": "ok"}


@app.post("/namuwiki/song-article", response_model=NamuWikiSongArticleResponse)
def create_namuwiki_song_article(
    payload: NamuWikiSongArticleRequest,
) -> NamuWikiSongArticleResponse:
    return NamuWikiSongArticleResponse(text=render_song_article(payload))


@app.post("/namuwiki/song-article/from-template", response_model=NamuWikiSongArticleResponse)
async def create_namuwiki_song_article_from_template(
    payload: NamuWikiTemplateSongArticleRequest,
) -> NamuWikiSongArticleResponse:
    try:
        text = await render_song_article_from_template(payload)
    except NamuWikiAiRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NamuWikiSongArticleResponse(text=text)


@app.post("/namuwiki/templates", response_model=NamuWikiTemplateDetail)
def create_namuwiki_template(payload: NamuWikiTemplateCreate) -> NamuWikiTemplateDetail:
    return save_template(payload)


@app.get("/namuwiki/templates", response_model=list[NamuWikiTemplateInfo])
def get_namuwiki_templates() -> list[NamuWikiTemplateInfo]:
    return list_templates()


@app.get("/namuwiki/templates/{template_id}", response_model=NamuWikiTemplateDetail)
def get_namuwiki_template(template_id: str) -> NamuWikiTemplateDetail:
    try:
        return get_template(template_id)
    except NamuWikiTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Template not found.") from exc


@app.post("/namuwiki/song-article/from-saved-template", response_model=NamuWikiSongArticleResponse)
async def create_namuwiki_song_article_from_saved_template(
    payload: NamuWikiSavedTemplateSongArticleRequest,
) -> NamuWikiSongArticleResponse:
    try:
        template = get_template(payload.template_id)
        text = await render_song_article_from_template(
            NamuWikiTemplateSongArticleRequest(
                template_example=template.template_example,
                song=payload.song,
                extra_instruction=payload.extra_instruction,
            )
        )
    except NamuWikiTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Template not found.") from exc
    except NamuWikiAiRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NamuWikiSongArticleResponse(text=text)


@app.get("/auth/google/start")
def start_google_auth(discord_user_id: str) -> RedirectResponse:
    """Discord 사용자 ID를 state로 담아 Google OAuth 로그인 화면으로 이동시킵니다."""
    if not google_oauth_configured():
        raise HTTPException(status_code=500, detail="Google OAuth가 설정되어 있지 않습니다.")
    return RedirectResponse(build_google_auth_url(discord_user_id))


@app.get("/auth/google/callback", response_class=HTMLResponse)
async def google_auth_callback(code: str, state: str) -> str:
    """Google OAuth callback에서 인증 code를 토큰으로 바꾸고 연결 완료 HTML을 보여줍니다."""
    await exchange_code_for_tokens(code, state)
    return """
    <html>
      <body>
        <h1>Google Calendar 연결 완료</h1>
        <p>이 페이지를 닫고 Discord로 돌아가도 됩니다.</p>
      </body>
    </html>
    """


@app.post("/artists", response_model=ArtistWithSources, status_code=status.HTTP_201_CREATED)
def create_artist(payload: ArtistCreate) -> dict:
    """API로 아티스트를 생성하고, X username이 있으면 출처도 함께 저장합니다."""
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
    """등록된 전체 아티스트와 연결된 출처 목록을 조회합니다."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM artists ORDER BY name").fetchall()
        return [_get_artist_with_sources(conn, row["id"]) for row in rows]


@app.get("/artists/{artist_id}", response_model=ArtistWithSources)
def get_artist(artist_id: int) -> dict:
    """특정 아티스트 한 명과 연결된 출처 목록을 조회합니다."""
    with get_connection() as conn:
        return _get_artist_with_sources(conn, artist_id)


@app.patch("/artists/{artist_id}", response_model=Artist)
def update_artist(artist_id: int, payload: ArtistUpdate) -> dict:
    """아티스트의 이름, 표시 이름, 메모를 부분 수정합니다."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

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
    """아티스트를 삭제하고 연결된 출처는 DB cascade 설정으로 함께 정리합니다."""
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
    """기존 아티스트에 X, 공식 사이트, 예매 사이트 같은 출처를 추가합니다."""
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
            raise HTTPException(status_code=409, detail="이미 등록된 출처입니다.") from exc

        row = conn.execute(
            "SELECT * FROM artist_sources WHERE id = %s",
            (source_id,),
        ).fetchone()
        return _source_row_to_dict(row)


@app.get("/artists/{artist_id}/sources", response_model=list[Source])
def list_artist_sources(artist_id: int) -> list[dict]:
    """특정 아티스트에 등록된 출처 목록을 조회합니다."""
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
    """특정 아티스트에 연결된 출처 하나를 삭제합니다."""
    with get_connection() as conn:
        _ensure_artist_exists(conn, artist_id)
        cursor = conn.execute(
            "DELETE FROM artist_sources WHERE id = %s AND artist_id = %s",
            (source_id, artist_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="출처를 찾을 수 없습니다.")
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/event-candidates", response_model=EventCandidate, status_code=status.HTTP_201_CREATED)
def create_event_candidate(payload: EventCandidateCreate) -> dict:
    """수동 또는 agent가 만든 공연/예매 일정 후보를 저장합니다."""
    data = payload.model_dump()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_candidates (
                artist_id, source_id, title, starts_at, venue, ticket_opens_at,
                ticket_closes_at, ticket_url, price_text, source_url, raw_text, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["artist_id"],
                data["source_id"],
                data["title"],
                data["starts_at"],
                data["venue"],
                data["ticket_opens_at"],
                data["ticket_closes_at"],
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
    """저장된 일정 후보를 조회하고, status_filter가 있으면 해당 상태만 반환합니다."""
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
    """아티스트가 실제로 존재하는지 확인하고 없으면 404 에러를 발생시킵니다."""
    row = conn.execute("SELECT id FROM artists WHERE id = %s", (artist_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="아티스트를 찾을 수 없습니다.")


def _get_artist_with_sources(conn: Connection, artist_id: int) -> dict:
    """아티스트 기본 정보에 출처 목록을 붙여 API 응답 형태로 만듭니다."""
    artist = row_to_dict(
        conn.execute("SELECT * FROM artists WHERE id = %s", (artist_id,)).fetchone()
    )
    if artist is None:
        raise HTTPException(status_code=404, detail="아티스트를 찾을 수 없습니다.")

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
    """DB에서 읽은 출처 row를 API 응답용 dict로 변환합니다."""
    source = row_to_dict(row)
    if source is None:
        raise HTTPException(status_code=404, detail="출처를 찾을 수 없습니다.")
    return source

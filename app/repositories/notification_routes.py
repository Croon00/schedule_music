from typing import Literal

from psycopg import errors

from app.core.db import get_connection, row_to_dict

NotificationItemType = Literal["notice", "release", "live_event", "ticket", "merch", "irrelevant"]
NOTIFICATION_ITEM_TYPES = ("notice", "release", "live_event", "ticket", "merch", "irrelevant")


class NotificationRouteConflictError(Exception): pass
class NotificationRouteNotFoundError(Exception): pass


def normalize_item_type(item_type: str) -> NotificationItemType:
    """알림 분류값을 DB에 저장 가능한 허용값으로 정규화한다."""
    value = item_type.strip().lower()
    if value not in NOTIFICATION_ITEM_TYPES: raise ValueError(f"Unsupported item type: {value}")
    return value  # type: ignore[return-value]


def create_notification_route(*, discord_user_id: str, guild_id: str, source_id: int, discord_channel_id: str) -> dict:
    """Discord 길드의 소스 알림 라우팅 규칙을 생성한다."""
    with get_connection() as conn:
        try:
            row = conn.execute("INSERT INTO notification_routes (discord_user_id, guild_id, source_id, item_type, discord_channel_id) VALUES (%s, %s, %s, 'all', %s) RETURNING *", (discord_user_id, guild_id, source_id, discord_channel_id)).fetchone(); conn.commit(); return row_to_dict(row)
        except errors.ForeignKeyViolation as exc: conn.rollback(); raise LookupError(f"Source #{source_id} was not found.") from exc
        except errors.UniqueViolation as exc: conn.rollback(); raise NotificationRouteConflictError("Route already exists.") from exc


def _select(where: str, values: list[object]) -> list[dict]:
    """알림 라우트와 소스·아티스트 표시 정보를 함께 조회한다."""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT r.*, s.value AS source_value, s.source_type, a.name AS artist_name FROM notification_routes r LEFT JOIN artist_sources s ON s.id = r.source_id LEFT JOIN artists a ON a.id = s.artist_id WHERE {where} ORDER BY r.source_id NULLS FIRST, r.item_type, r.id", values).fetchall()
    return [row_to_dict(row) for row in rows]


def list_notification_routes(*, guild_id: str, source_id: int | None = None, include_inactive: bool = False) -> list[dict]:
    """한 길드의 알림 라우트를 활성 상태 기준으로 조회한다."""
    clauses, values = ["r.guild_id = %s"], [guild_id]
    if source_id is not None: clauses.append("r.source_id = %s"); values.append(source_id)
    if not include_inactive: clauses.append("r.is_active = TRUE")
    return _select(" AND ".join(clauses), values)


def delete_notification_route(*, guild_id: str, route_id: int) -> bool:
    """길드 범위에서 라우트를 삭제하고 삭제 여부를 반환한다."""
    with get_connection() as conn:
        result = conn.execute("DELETE FROM notification_routes WHERE id = %s AND guild_id = %s", (route_id, guild_id)); conn.commit(); return result.rowcount > 0


def get_notification_route(*, guild_id: str, route_id: int) -> dict:
    """테스트 전송 등에 사용할 라우트 한 건을 조회한다."""
    routes = _select("r.id = %s AND r.guild_id = %s", [route_id, guild_id])
    if not routes: raise NotificationRouteNotFoundError(f"Route #{route_id} was not found.")
    return routes[0]


def set_source_active_for_user(*, discord_user_id: str, source_id: int, is_active: bool) -> dict:
    """소유자 또는 시스템 소스 권한이 있는 사용자의 수집 상태를 변경한다."""
    with get_connection() as conn:
        row = conn.execute("UPDATE artist_sources s SET is_active = %s, updated_at = CURRENT_TIMESTAMP FROM artists a WHERE s.id = %s AND a.id = s.artist_id AND (a.discord_user_id = %s OR a.discord_user_id LIKE 'system:%%') RETURNING s.id, s.source_type, s.label, s.value, s.is_active, a.name AS artist_name, a.display_name", (is_active, source_id, discord_user_id)).fetchone(); conn.commit()
    result = row_to_dict(row)
    if result is None: raise LookupError(f"Source #{source_id} was not found or is not permitted.")
    return result


def find_notification_routes_for_item(*, source_id: int) -> list[dict]:
    """새 수집 항목의 source에 연결된 활성 알림 라우트를 찾는다."""
    return _select("r.is_active = TRUE AND (r.source_id = %s OR r.source_id IS NULL)", [source_id])


def update_source_item_classification(*, source_item_id: int, item_type: str, confidence: float | None) -> None:
    """수집 원문의 AI 분류 결과와 신뢰도를 저장한다."""
    with get_connection() as conn: conn.execute("UPDATE source_items SET item_type = %s, classification_confidence = %s WHERE id = %s", (normalize_item_type(item_type), confidence, source_item_id)); conn.commit()

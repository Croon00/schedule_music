from __future__ import annotations

from typing import Literal

from psycopg import errors

from app.core.db import get_connection, row_to_dict


NotificationItemType = Literal[
    "notice",
    "release",
    "live_event",
    "ticket",
    "merch",
    "irrelevant",
    "all_non_ticket",
]

NOTIFICATION_ITEM_TYPES: tuple[str, ...] = (
    "notice",
    "release",
    "live_event",
    "ticket",
    "merch",
    "irrelevant",
    # Artist-specific catch-all: sends every classified post except tickets.
    "all_non_ticket",
)


class NotificationRouteConflictError(Exception):
    """Raised when the same guild/source/type/channel route already exists."""


class NotificationRouteNotFoundError(Exception):
    """Raised when a route cannot be found for the requested owner scope."""


def normalize_item_type(item_type: str) -> NotificationItemType:
    """Validate a user supplied item type before it reaches route storage."""
    normalized = item_type.strip().lower()
    if normalized not in NOTIFICATION_ITEM_TYPES:
        allowed = ", ".join(NOTIFICATION_ITEM_TYPES)
        raise ValueError(f"지원하지 않는 item_type입니다. 사용 가능: {allowed}")
    return normalized  # type: ignore[return-value]


def create_notification_route(
    *,
    discord_user_id: str,
    guild_id: str,
    source_id: int | None,
    item_type: str,
    discord_channel_id: str,
) -> dict:
    """Create a Discord routing rule for one source/type pair in one guild."""
    normalized_item_type = normalize_item_type(item_type)
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO notification_routes (
                    discord_user_id, guild_id, source_id, item_type, discord_channel_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    discord_user_id,
                    guild_id,
                    source_id,
                    normalized_item_type,
                    discord_channel_id,
                ),
            )
            route = cursor.fetchone()
            conn.commit()
            return row_to_dict(route)
        except errors.ForeignKeyViolation as exc:
            conn.rollback()
            raise LookupError(f"source #{source_id}를 찾을 수 없습니다.") from exc
        except errors.UniqueViolation as exc:
            conn.rollback()
            raise NotificationRouteConflictError("이미 같은 라우팅이 등록되어 있습니다.") from exc


def list_notification_routes(
    *,
    guild_id: str,
    source_id: int | None = None,
    include_inactive: bool = False,
) -> list[dict]:
    """List routes for one Discord guild, optionally scoped to one source."""
    clauses = ["r.guild_id = %s"]
    values: list[object] = [guild_id]
    if source_id is not None:
        clauses.append("r.source_id = %s")
        values.append(source_id)
    if not include_inactive:
        clauses.append("r.is_active = TRUE")

    sql = f"""
        SELECT
            r.*,
            s.value AS source_value,
            s.source_type,
            a.name AS artist_name
        FROM notification_routes r
        LEFT JOIN artist_sources s ON s.id = r.source_id
        LEFT JOIN artists a ON a.id = s.artist_id
        WHERE {" AND ".join(clauses)}
        ORDER BY r.source_id NULLS FIRST, r.item_type, r.id
    """
    with get_connection() as conn:
        rows = conn.execute(sql, values).fetchall()
        return [row_to_dict(row) for row in rows]


def delete_notification_route(
    *,
    guild_id: str,
    route_id: int,
) -> bool:
    """Delete one route in the current guild; returns False if it did not exist."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM notification_routes
            WHERE id = %s AND guild_id = %s
            """,
            (route_id, guild_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_notification_route(
    *,
    guild_id: str,
    route_id: int,
) -> dict:
    """Fetch one route for commands such as route_test."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                r.*,
                s.value AS source_value,
                s.source_type,
                a.name AS artist_name
            FROM notification_routes r
            LEFT JOIN artist_sources s ON s.id = r.source_id
            LEFT JOIN artists a ON a.id = s.artist_id
            WHERE r.id = %s AND r.guild_id = %s
            """,
            (route_id, guild_id),
        ).fetchone()
    route = row_to_dict(row)
    if route is None:
        raise NotificationRouteNotFoundError(f"route #{route_id}를 찾을 수 없습니다.")
    return route


def find_notification_routes_for_item(
    *,
    source_id: int,
    item_type: str,
) -> list[dict]:
    """Return active exact routes plus artist-specific non-ticket catch-all routes."""
    normalized_item_type = normalize_item_type(item_type)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                s.value AS source_value,
                s.source_type,
                a.name AS artist_name
            FROM notification_routes r
            LEFT JOIN artist_sources s ON s.id = r.source_id
            LEFT JOIN artists a ON a.id = s.artist_id
            WHERE r.is_active = TRUE
                AND (
                    (r.item_type = %s AND (r.source_id = %s OR r.source_id IS NULL))
                    OR (
                        r.item_type = 'all_non_ticket'
                        AND r.source_id = %s
                        AND %s <> 'ticket'
                    )
                )
            ORDER BY r.source_id NULLS LAST, r.id
            """,
            (normalized_item_type, source_id, source_id, normalized_item_type),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def update_source_item_classification(
    *,
    source_item_id: int,
    item_type: str,
    confidence: float | None,
) -> None:
    """Persist the classification result for later debugging and cost review."""
    normalized_item_type = normalize_item_type(item_type)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE source_items
            SET item_type = %s, classification_confidence = %s
            WHERE id = %s
            """,
            (normalized_item_type, confidence, source_item_id),
        )
        conn.commit()

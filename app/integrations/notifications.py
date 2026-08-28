"""Deprecated compatibility import; notification storage lives in repositories."""

from app.repositories.notification_routes import (
    NOTIFICATION_ITEM_TYPES,
    NotificationItemType,
    NotificationRouteConflictError,
    NotificationRouteNotFoundError,
    create_notification_route,
    delete_notification_route,
    find_notification_routes_for_item,
    get_notification_route,
    list_notification_routes,
    list_undelivered_items_for_route,
    normalize_item_type,
    record_notification_delivery,
    set_source_active_for_user,
    update_source_item_classification,
)

__all__ = [name for name in globals() if not name.startswith("_")]

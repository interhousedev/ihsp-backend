"""Factories for notify and admin tests."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import NotificationStatus
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.contracts.links import ResourceRef
from app.shared.ids import new_id
from app.shared.notifications import NotificationType

NOW = datetime.fromisoformat("2026-10-06T09:00:00+00:00")


def make_user(
    *roles: Role,
    locale: str = "en",
    status: UserStatus = UserStatus.ACTIVE,
    first_name: str = "Aliya",
    last_name: str = "Karimova",
    user_id: UUID | None = None,
) -> UserRef:
    """A user reference (a student when no role is given)."""
    return UserRef(
        id=user_id or new_id(),
        login="aliya.karimova",
        first_name=first_name,
        last_name=last_name,
        middle_name=None,
        roles=frozenset(roles or (Role.STUDENT,)),
        status=status,
        locale=locale,
        emis_status=None,
    )


def make_notification(
    user_id: UUID,
    notification_type: NotificationType = NotificationType.MARKS,
    *,
    payload: dict[str, Any] | None = None,
    scheduled_at: datetime = NOW,
    created_at: datetime | None = None,
    status: NotificationStatus = NotificationStatus.PENDING,
    broadcast_id: UUID | None = None,
    dedupe_key: str | None = None,
) -> Notification:
    """A notification entity that is due at `scheduled_at`."""
    notification_id = new_id()
    return Notification(
        id=notification_id,
        user_id=user_id,
        type=notification_type,
        payload=payload if payload is not None else {},
        dedupe_key=dedupe_key or f"test:{notification_id}",
        scheduled_at=scheduled_at,
        created_at=created_at or scheduled_at,
        broadcast_id=broadcast_id,
        status=status,
    )


def make_resource(
    lesson_id: UUID,
    *,
    role: str = "material",
    title: str = "Lecture 5.pdf",
    short_url: str = "https://s.ihsu.uz/9d-K4m_x",
    author: str = "Aleksey",
    hidden: bool = False,
) -> ResourceRef:
    """A lesson resource as LinksApi returns it."""
    return ResourceRef(
        link_id=new_id(),
        lesson_id=lesson_id,
        role=role,  # type: ignore[arg-type]
        kind="file",
        short_url=short_url,
        title=title,
        author_id=new_id(),
        author_first_name=author,
        hidden=hidden,
        file_id=None,
    )

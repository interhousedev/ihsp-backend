"""Use case: a course admin sends an update to the students of a course.

The caller (the LMS route) has already checked that the actor may broadcast in the
course and gives the enrolled students. Each student gets an in-app notification of
the `broadcast` type, which the dispatcher also sends as Web Push and to Telegram, and
the message is kept in the course's broadcast history.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from app.modules.notify.application.format import esc
from app.modules.notify.domain.course_broadcast import (
    CourseBroadcast,
    CourseBroadcastForbiddenError,
    CourseBroadcastNotFoundError,
    clean_broadcast_text,
)
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

HISTORY_LIMIT = 50


@dataclass(frozen=True, slots=True)
class SentCourseBroadcast:
    """The stored broadcast and who it was sent to."""

    broadcast: CourseBroadcast
    user_ids: tuple[UUID, ...]


class CourseBroadcastService:
    """Creates the notifications of a course broadcast and lists the history."""

    def __init__(
        self, *, uow_factory: Callable[[], NotifyUnitOfWork], clock: Clock
    ) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def send(
        self,
        *,
        course_id: UUID,
        course_slug: str,
        author_id: UUID,
        title: str,
        body: str,
        recipient_ids: Sequence[UUID],
    ) -> SentCourseBroadcast:
        """Notify the recipients (the author is never one of them) and store it."""
        clean_title, clean_body = clean_broadcast_text(title, body)
        broadcast = CourseBroadcast(
            id=new_id(),
            course_id=course_id,
            author_id=author_id,
            title=clean_title,
            body=clean_body,
            created_at=self.clock.now(),
        )
        users = tuple(dict.fromkeys(uid for uid in recipient_ids if uid != author_id))
        async with self.uow_factory() as uow:
            await uow.course_broadcasts.add(broadcast)
            uow.notify(*(_draft(broadcast, course_slug, user_id) for user_id in users))
            await uow.commit()
        return SentCourseBroadcast(broadcast=broadcast, user_ids=users)

    async def update(
        self,
        *,
        course_id: UUID,
        broadcast_id: UUID,
        actor_id: UUID,
        is_course_admin: bool,
        title: str | None,
        body: str | None,
    ) -> CourseBroadcast:
        """Edit the title and text; only the author or a course admin may.

        The students' notifications are rewritten in place and carry an edit mark;
        pushes and Telegram messages already delivered stay as they were.
        """
        async with self.uow_factory() as uow:
            current = await uow.course_broadcasts.get(broadcast_id)
            if current is None or current.course_id != course_id:
                raise CourseBroadcastNotFoundError(
                    params={"broadcast_id": str(broadcast_id)}
                )
            if current.author_id != actor_id and not is_course_admin:
                raise CourseBroadcastForbiddenError()
            clean_title, clean_body = clean_broadcast_text(
                current.title if title is None else title,
                current.body if body is None else body,
            )
            now = self.clock.now()
            changed = replace(
                current, title=clean_title, body=clean_body, updated_at=now
            )
            await uow.course_broadcasts.update(changed)
            await uow.notifications.update_course_broadcast(
                broadcast_id, title=clean_title, text=esc(clean_body), edited_at=now
            )
            await uow.commit()
        return changed

    async def history(self, course_id: UUID) -> list[CourseBroadcast]:
        """Return the newest broadcasts of the course first."""
        async with self.uow_factory() as uow:
            return await uow.course_broadcasts.list_for_course(
                course_id, limit=HISTORY_LIMIT
            )


def _draft(
    broadcast: CourseBroadcast, course_slug: str, user_id: UUID
) -> NotificationDraft:
    """The notification of one student; `text` is Telegram HTML, so it is escaped."""
    return NotificationDraft(
        user_id=user_id,
        type=NotificationType.BROADCAST,
        payload={
            "title": broadcast.title,
            "text": esc(broadcast.body),
            "course_id": str(broadcast.course_id),
            "course_slug": course_slug,
            "course_broadcast_id": str(broadcast.id),
        },
        dedupe_key=f"course_broadcast:{broadcast.id}:{user_id}",
    )

"""Small helpers shared by the schedule use cases."""

import datetime as dt
from collections.abc import Callable, Collection
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import (
    PersonData,
    SubjectRefData,
)
from app.modules.academic.domain.schedule.subject import Subject, subject_name
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.tasks import TaskKicker

UowFactory = Callable[[], ScheduleUnitOfWork]
DEFAULT_LOCALE = "ru"
KICK_CHUNK = 200


def today(clock: Clock) -> dt.date:
    """Return today's date in Tashkent."""
    return local_today(clock)


async def caller_locale(identity: IdentityDirectory, actor: Actor) -> str:
    """Return the locale of the user, falling back to the default."""
    user = await identity.get_user(actor.user_id)
    return user.locale if user else DEFAULT_LOCALE


def person_data(user: UserRef) -> PersonData:
    """Map a UserRef to PersonRef."""
    return PersonData(id=user.id, first_name=user.first_name, last_name=user.last_name)


async def person_map(
    identity: IdentityDirectory, user_ids: Collection[UUID | None]
) -> dict[UUID, PersonData]:
    """Return PersonRefs of the users that exist."""
    ids = sorted({uid for uid in user_ids if uid is not None})
    if not ids:
        return {}
    users = await identity.get_users(ids)
    return {uid: person_data(user) for uid, user in users.items()}


def subject_data(subject: Subject, locale: str) -> SubjectRefData:
    """Map a subject to SubjectRef in the locale."""
    return SubjectRefData(
        id=subject.id, name=subject_name(subject, locale), short_name=subject.short_name
    )


def kick_after_commit(
    uow: ScheduleUnitOfWork, kicker: TaskKicker, task: str, **kwargs: Any
) -> None:
    """Start a background task once the transaction is committed."""

    async def hook() -> None:
        await kicker.kick(task, **kwargs)

    uow.after_commit(hook)


def kick_recompute_due_dates(
    uow: ScheduleUnitOfWork, kicker: TaskKicker, lesson_ids: Collection[UUID]
) -> None:
    """Ask classwork to recompute homework due dates of the lessons (chunked)."""
    ids = [str(lesson_id) for lesson_id in lesson_ids]
    for start in range(0, len(ids), KICK_CHUNK):
        kick_after_commit(
            uow,
            kicker,
            "academic.recompute_due_dates",
            lesson_ids=ids[start : start + KICK_CHUNK],
        )


def kick_generation(
    uow: ScheduleUnitOfWork, kicker: TaskKicker, clock: Clock, term_id: UUID
) -> None:
    """Ask the worker to regenerate the term's lessons from today."""
    kick_after_commit(
        uow,
        kicker,
        "academic.generate_lessons",
        term_id=str(term_id),
        from_date=today(clock).isoformat(),
    )

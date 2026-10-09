"""Who may manage the controls of a subject in a group."""

import datetime as dt
from collections.abc import Collection
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentReader,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.errors import NotAssessmentTeacherError
from app.shared.actor import Actor, Role


async def ensure_may_manage(
    reader: AssessmentReader,
    actor: Actor,
    subject_id: UUID,
    audience: Collection[str],
    today: dt.date,
) -> None:
    """Raise unless the actor is an admin or teaches the subject in every group."""
    if actor.has(Role.ADMIN):
        return
    if not actor.has(Role.TEACHER):
        raise NotAssessmentTeacherError()
    taught = await reader.taught_groups(actor.user_id, today)
    if not audience_keys.group_ids(audience) <= taught.get(subject_id, set()):
        raise NotAssessmentTeacherError()

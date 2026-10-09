"""Checks that need the database: the subject, the groups and the lesson exist."""

from collections.abc import Collection
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentReader,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.errors import (
    AssessmentSubjectNotFoundError,
    InvalidAssessmentError,
)


async def check_references(
    reader: AssessmentReader,
    *,
    subject_id: UUID,
    audience: Collection[str],
    lesson_id: UUID | None,
) -> None:
    """Raise unless the subject, every group and the linked lesson are real."""
    if subject_id not in await reader.subjects([subject_id]):
        raise AssessmentSubjectNotFoundError(params={"subject_id": str(subject_id)})
    groups = audience_keys.group_ids(audience)
    if set(await reader.group_names(groups)) != groups:
        raise InvalidAssessmentError(params={"field": "audience"})
    if lesson_id is not None and await reader.lesson_subject(lesson_id) != subject_id:
        raise InvalidAssessmentError(params={"field": "lesson_id"})

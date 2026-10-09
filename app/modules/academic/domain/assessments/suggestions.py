"""Controls suggested by EMIS lessons marked as a midterm or a final.

EMIS control *weeks* are right, but the data is filled in late and many teachers have
no plan there. So a control lesson inside a week Administration set is trusted
(planned); one outside every week only hints (tentative) until a teacher or
Administration confirms, edits or dismisses it.
"""

from collections.abc import Sequence
from dataclasses import replace

from app.modules.academic.domain.assessments.periods import TermControls, control_on
from app.modules.academic.domain.assessments.records import (
    Assessment,
    LessonCandidate,
    NewAssessment,
)
from app.modules.academic.domain.assessments.rules import is_duplicate

TITLE_MAX = 200


def suggestions_from_lessons(
    lessons: Sequence[LessonCandidate],
    existing: Sequence[Assessment],
    terms: Sequence[TermControls],
) -> list[NewAssessment]:
    """Return the controls EMIS lessons suggest and nobody has stored yet.

    A double period gives one control, not two. Lessons that already have a control
    (by link or by the duplicate rule) give nothing.
    """
    known: list[Assessment | NewAssessment] = list(existing)
    linked = {a.lesson_id for a in existing if a.lesson_id is not None}
    created: list[NewAssessment] = []
    for lesson in sorted(lessons, key=lambda x: (x.date, x.starts_at, x.lesson_id)):
        if lesson.lesson_id in linked:
            continue
        new = _from_lesson(lesson, terms)
        if any(is_duplicate(new, other) for other in known):
            continue
        created.append(new)
        known.append(new)
    return created


def promote_inside_weeks(
    existing: Sequence[Assessment], terms: Sequence[TermControls]
) -> list[Assessment]:
    """Return the tentative EMIS controls that now fall inside a control week.

    Administration may set the weeks after EMIS lessons were first read; those
    suggestions become planned and learn their control week.
    """
    promoted: list[Assessment] = []
    for a in existing:
        if a.status != "tentative" or a.source != "emis":
            continue
        control = control_on(a.kind, a.date, terms)
        if control is not None:
            promoted.append(replace(a, status="planned", control=control))
    return promoted


def _from_lesson(
    lesson: LessonCandidate, terms: Sequence[TermControls]
) -> NewAssessment:
    control = control_on(lesson.kind, lesson.date, terms)
    return NewAssessment(
        subject_id=lesson.subject_id,
        audience=lesson.audience,
        kind=lesson.kind,
        title=(lesson.topic or "").strip()[:TITLE_MAX],
        date=lesson.date,
        lesson_id=lesson.lesson_id,
        starts_at=lesson.starts_at,
        room=lesson.room,
        status="tentative" if control is None else "planned",
        source="emis",
        note=None,
        created_by=None,
        control=control,
    )

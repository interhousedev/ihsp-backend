"""Which subjects belong to a semester on the student's semester pages."""

from collections.abc import Collection, Iterable
from uuid import UUID

from app.modules.academic.domain.marks.read_models import ResultRow


def has_marks(row: ResultRow) -> bool:
    """Return True if a result holds a mark; sync also stores empty rows."""
    return row.value is not None or row.marks_count > 0


def semester_subject_ids(
    *,
    rows: Iterable[ResultRow],
    planned: Collection[UUID] | None,
    group_subjects: Collection[UUID],
    taught: Collection[UUID],
    is_current: bool,
) -> set[UUID]:
    """Return the subjects a semester shows.

    `rows` are the student's results of this semester, `planned` the curriculum's
    subjects of this semester (None when the curriculum does not list it, so nothing
    can be ruled out), `group_subjects` the group's cumulative subject list and
    `taught` the subjects with lessons inside the semester's dates.

    A mark is never hidden. Without marks a subject stays only if the curriculum plans
    it or it has lessons in the semester; this drops subjects of past semesters.
    """
    results = [r for r in rows if r.subject_id is not None]
    candidates = {r.subject_id for r in results if r.subject_id is not None}
    if is_current:
        candidates |= set(group_subjects)
    if planned is None:
        return candidates
    kept = {r.subject_id for r in results if r.subject_id is not None and has_marks(r)}
    kept |= candidates & set(taught)
    kept |= set(planned) if is_current else candidates & set(planned)
    return kept

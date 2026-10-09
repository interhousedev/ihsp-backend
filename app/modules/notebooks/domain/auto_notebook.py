"""Which lesson materials an auto notebook keeps, and in which order (NB-AUTO)."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.modules.notebooks.domain.limits import AUTO_SYNC_STALE_AFTER


def lesson_ref_key(link_id: UUID) -> str:
    """The duplicate key of a lesson resource source (`lesson:<link_id>`)."""
    return f"lesson:{link_id}"


@dataclass(frozen=True, slots=True)
class AutoCandidate:
    """A lesson resource the student may see, before it becomes a source.

    Attributes:
        link_id: The lesson resource (a link of the links module).
        lesson_id: The lesson it is attached to.
        lesson_date: When that lesson is held.
        role: `material` (teacher or EMIS) or `attachment` (a student's file).
        own: The student attached it themselves.
    """

    link_id: UUID
    lesson_id: UUID
    lesson_date: date
    role: str
    own: bool = False

    @property
    def ref_key(self) -> str:
        """The duplicate key of the source this resource becomes."""
        return lesson_ref_key(self.link_id)

    @property
    def from_classmates(self) -> bool:
        """A file another student attached to the lesson."""
        return self.role == "attachment" and not self.own

    @property
    def priority(self) -> int:
        """0 teacher material, 1 the student's own file, 2 a classmate's file."""
        if self.role == "material":
            return 0
        return 1 if self.own else 2


def rank_candidates(
    candidates: Sequence[AutoCandidate],
    *,
    include_classmates: bool,
    excluded: Collection[str],
) -> list[AutoCandidate]:
    """The candidates an auto notebook wants, best first.

    Excluded resources are always left out and classmates' files only when the
    student switched them on. Teacher materials come before the student's own
    files, those before classmates' files; newest lesson first within a group.
    Every resource appears once. The notebook keeps as many from the top as fit.
    """
    seen: set[str] = set()
    wanted: list[AutoCandidate] = []
    for item in candidates:
        if item.ref_key in excluded or item.ref_key in seen:
            continue
        if item.from_classmates and not include_classmates:
            continue
        seen.add(item.ref_key)
        wanted.append(item)
    wanted.sort(key=lambda item: (item.priority, -item.lesson_date.toordinal()))
    return wanted


def sync_is_stale(synced_at: datetime | None, now: datetime) -> bool:
    """True when an auto notebook was never synced or not for a while."""
    return synced_at is None or now - synced_at >= AUTO_SYNC_STALE_AFTER

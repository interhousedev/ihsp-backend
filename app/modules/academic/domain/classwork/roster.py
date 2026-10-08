"""Who is expected at a lesson (ACA-2, ACA-6, STF-8)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys


@dataclass(frozen=True, slots=True)
class RosterStudent:
    """A student of the lesson's groups with the names to show."""

    user_id: UUID
    first_name: str
    last_name: str
    group_id: UUID
    group_name: str
    subgroup: int | None

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Stable order: last name, first name, group name."""
        return (self.last_name.casefold(), self.first_name.casefold(), self.group_name)


@dataclass(frozen=True, slots=True)
class Roster:
    """Expected students plus those without a subgroup in a subgroup lesson."""

    expected: tuple[RosterStudent, ...]
    unassigned: tuple[RosterStudent, ...]

    @property
    def entries(self) -> tuple[RosterStudent, ...]:
        """Positions 0..n-1 run over expected, then unassigned."""
        return self.expected + self.unassigned

    def student_at(self, position: int) -> RosterStudent | None:
        """Return the student at a position, or None."""
        entries = self.entries
        if 0 <= position < len(entries):
            return entries[position]
        return None

    def expected_ids(self) -> set[UUID]:
        """User ids that count by default."""
        return {student.user_id for student in self.expected}

    def unassigned_ids(self) -> set[UUID]:
        """User ids that count only if the teacher marks them."""
        return {student.user_id for student in self.unassigned}


def _targets(keys: Iterable[str]) -> tuple[set[UUID], dict[UUID, set[int]]]:
    whole: set[UUID] = set()
    parts: dict[UUID, set[int]] = {}
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        if subgroup is None:
            whole.add(group_id)
        else:
            parts.setdefault(group_id, set()).add(subgroup)
    return whole, parts


def build_roster(
    audience: Sequence[str],
    students: Iterable[RosterStudent],
    extra: Iterable[RosterStudent] = (),
) -> Roster:
    """Split the students of the audience's groups into expected and unassigned.

    A whole-group key expects every student of the group; a subgroup key expects
    the students of that subgroup and lists the group's students without a
    subgroup separately. ``extra`` are students saved in an earlier attendance
    snapshot who are no longer in the groups; they stay expected.
    """
    whole, parts = _targets(audience)
    expected: dict[UUID, RosterStudent] = {}
    unassigned: dict[UUID, RosterStudent] = {}
    for student in students:
        if student.group_id in whole:
            expected[student.user_id] = student
        elif student.group_id in parts:
            if student.subgroup is None:
                unassigned[student.user_id] = student
            elif student.subgroup in parts[student.group_id]:
                expected[student.user_id] = student
    for student in extra:
        if student.user_id not in expected and student.user_id not in unassigned:
            expected[student.user_id] = student
    return Roster(
        expected=tuple(sorted(expected.values(), key=lambda s: s.sort_key)),
        unassigned=tuple(sorted(unassigned.values(), key=lambda s: s.sort_key)),
    )

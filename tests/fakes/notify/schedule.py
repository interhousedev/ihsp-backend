"""The part of ScheduleQueries that broadcasts use."""

from collections.abc import Sequence
from uuid import UUID


class FakeScheduleQueries:
    """Students of groups and of semesters kept in dictionaries."""

    def __init__(self) -> None:
        """Start empty."""
        self.group_users: dict[UUID, list[UUID]] = {}
        self.semester_users: dict[int, list[UUID]] = {}
        self.calls: list[tuple[tuple[UUID, ...], tuple[int, ...]]] = []

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Return users of the groups, or of the groups in the semesters."""
        self.calls.append((tuple(group_ids), tuple(semesters)))
        found: list[UUID] = []
        for group_id in group_ids:
            found.extend(self.group_users.get(group_id, []))
        if not group_ids:
            for semester in semesters:
                found.extend(self.semester_users.get(semester, []))
        return found

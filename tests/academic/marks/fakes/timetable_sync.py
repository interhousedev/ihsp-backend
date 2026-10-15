"""A TimetableSync that records the (group, student) pairs it was asked through."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FakeOutcome:
    """The only thing the run looks at."""

    status: str


class FakeTimetableSync:
    """Students in ``fail_for`` have no working EMIS link (status emis_unavailable)."""

    def __init__(self) -> None:
        """Start empty."""
        self.calls: list[tuple[UUID, UUID, bool]] = []
        self.fail_for: set[UUID] = set()
        self.raise_for: set[UUID] = set()
        self.resyncs: list[
            tuple[UUID, frozenset[tuple[str, int]], list[list[UUID]]]
        ] = []

    async def execute(
        self, *, group_id: UUID, user_id: UUID, refresh_bells: bool = True
    ) -> FakeOutcome:
        """Record the call; answer like the real sync for broken links."""
        self.calls.append((group_id, user_id, refresh_bells))
        if user_id in self.raise_for:
            raise RuntimeError("boom")
        return FakeOutcome("emis_unavailable" if user_id in self.fail_for else "synced")

    async def resync_materials(
        self,
        *,
        group_id: UUID,
        terms: Collection[tuple[str, int]],
        fetchers: Sequence[Sequence[UUID]],
    ) -> int:
        """Record which students would read EMIS for the group."""
        self.resyncs.append(
            (group_id, frozenset(terms), [list(slot) for slot in fetchers])
        )
        return 1

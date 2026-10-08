"""Write one student's fetched EMIS ratings: marks, results and GPA (SYNC-5..7)."""

from dataclasses import dataclass, field

from app.modules.academic.application.marks.ports.unit_of_work import MarksUnitOfWork
from app.modules.academic.domain.marks.alerts import (
    AddedMark,
    GpaChange,
    SubjectChange,
)
from app.modules.academic.domain.marks.diff import (
    MarkKey,
    diff,
    split_restored,
    with_ordinals,
)
from app.modules.academic.domain.marks.names import localized
from app.modules.academic.domain.marks.records import NewMark
from app.modules.academic.domain.marks.results import (
    compute_gpa,
    compute_subject_result,
)
from app.modules.academic.domain.marks.sync import FetchedRatings, StudentSyncState
from app.shared.clock import Clock


@dataclass(slots=True)
class ApplyResult:
    """What changed while writing one student's ratings."""

    added: list[AddedMark] = field(default_factory=list)
    subject_changes: list[SubjectChange] = field(default_factory=list)
    gpa_changes: list[GpaChange] = field(default_factory=list)


class ApplyRatings:
    """Diffs fetched ratings against stored marks and recomputes results."""

    def __init__(self, *, clock: Clock) -> None:
        """Store the clock used for removal times."""
        self._clock = clock

    async def execute(
        self,
        uow: MarksUnitOfWork,
        state: StudentSyncState,
        fetched: list[FetchedRatings],
        *,
        locale: str,
    ) -> ApplyResult:
        """Apply every fetched subject, then recompute the touched semesters' GPA."""
        result = ApplyResult()
        touched: set[int] = set()
        for item in fetched:
            change = await self._apply_subject(uow, state, item, locale, result)
            if change is not None:
                result.subject_changes.append(change)
                touched.add(item.ratings.semester)
        for semester in sorted(touched):
            result.gpa_changes.append(await self._refresh_gpa(uow, state, semester))
        return result

    async def _apply_subject(
        self,
        uow: MarksUnitOfWork,
        state: StudentSyncState,
        item: FetchedRatings,
        locale: str,
        result: ApplyResult,
    ) -> SubjectChange | None:
        """Write one subject; return None when its EMIS response is unchanged."""
        subject_id, ratings = item.subject.subject_id, item.ratings
        old = await uow.results.get(state.user_id, ratings.semester, subject_id)
        if old is not None and old.emis_hash == ratings.payload_hash:
            return None
        new_keys = await self._sync_marks(uow, state, item)
        values = await uow.marks.values_by_type(
            state.user_id, subject_id, ratings.semester
        )
        snapshot = compute_subject_result(
            values,
            emis_rating=ratings.semester_rating,
            emis_hash=ratings.payload_hash,
        )
        await uow.results.save(state.user_id, ratings.semester, subject_id, snapshot)
        name = localized(item.subject.name, locale)
        result.added.extend(
            AddedMark(subject_id, name, ratings.semester, key) for key in new_keys
        )
        return SubjectChange(subject_id, name, ratings.semester, old, snapshot)

    async def _sync_marks(
        self, uow: MarksUnitOfWork, state: StudentSyncState, item: FetchedRatings
    ) -> list[MarkKey]:
        """Insert, remove and restore marks; return the really new keys."""
        subject_id, semester = item.subject.subject_id, item.ratings.semester
        stored = await uow.marks.list_for_subject(state.user_id, subject_id, semester)
        active = {m.key: m for m in stored if not m.removed}
        gone = {m.key: m for m in stored if m.removed}
        added, removed = diff(active.keys(), with_ordinals(item.ratings.marks))
        new_keys, restored = split_restored(added, gone.keys())
        if removed:
            await uow.marks.set_removed(
                [active[key].id for key in removed], self._clock.now()
            )
        if restored:
            await uow.marks.set_removed([gone[key].id for key in restored], None)
        await self._insert(uow, state, item, new_keys)
        return new_keys

    async def _insert(
        self,
        uow: MarksUnitOfWork,
        state: StudentSyncState,
        item: FetchedRatings,
        keys: list[MarkKey],
    ) -> None:
        """Insert new marks, each attached to its lesson when there is one."""
        if not keys:
            return
        subject_id = item.subject.subject_id
        lessons = await uow.lessons.match(
            group_id=state.group_id,
            subgroup=state.subgroup,
            pairs={(subject_id, key.date) for key in keys},
        )
        await uow.marks.add(
            [
                NewMark(
                    student_id=state.user_id,
                    subject_id=subject_id,
                    semester=item.ratings.semester,
                    key=key,
                    lesson_id=lessons.get((subject_id, key.date)),
                )
                for key in keys
            ]
        )

    async def _refresh_gpa(
        self, uow: MarksUnitOfWork, state: StudentSyncState, semester: int
    ) -> GpaChange:
        """Recompute the semester GPA row and return its old and new values."""
        old = await uow.results.get(state.user_id, semester, None)
        values = await uow.marks.semester_values(state.user_id, semester)
        snapshot = compute_gpa(values)
        await uow.results.save(state.user_id, semester, None, snapshot)
        return GpaChange(semester, None if old is None else old.value, snapshot.value)

"""Which lessons of a divided group a student sees, and whose subgroup each is."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.schedule.subgroup_marks import (
    SubgroupMark,
    lesson_subgroups,
    place_lessons,
)
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id

GROUP = new_id()
OTHER_GROUP = new_id()
DAY = dt.date(2026, 10, 7)
ENGLISH = new_id()
IT = new_id()


def _ref(period: int, subject: UUID, *audience: str) -> LessonRef:
    start = dt.datetime(2026, 10, 7, 8, tzinfo=dt.UTC) + dt.timedelta(hours=period)
    return LessonRef(
        id=new_id(),
        date=DAY,
        period=period,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=80),
        subject_id=subject,
        subject_name="x",
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name=None,
        audience=audience,
        group_names=(),
        status="scheduled",
        topic=None,
        homework_text=None,
        homework_due_date=None,
    )


def _summary(
    placed: list[tuple[LessonRef, SubgroupMark | None]],
) -> list[tuple[int, int | None, bool | None]]:
    return [
        (
            ref.period,
            mark.subgroup_id if mark else None,
            mark.is_own_subgroup if mark else None,
        )
        for ref, mark in placed
    ]


def test_lesson_subgroups_reads_the_keys_of_the_group() -> None:
    assert lesson_subgroups((str(GROUP),), GROUP) is None
    assert lesson_subgroups((f"{GROUP}:2", f"{OTHER_GROUP}:1"), GROUP) == {2}
    assert lesson_subgroups((f"{OTHER_GROUP}:1",), GROUP) == set()


def test_whole_group_lessons_carry_no_mark() -> None:
    placed = place_lessons([_ref(1, ENGLISH, str(GROUP))], GROUP, "2TN2", 1)

    assert _summary(placed) == [(1, None, None)]


def test_the_other_subgroup_fills_a_free_slot_marked_as_not_own() -> None:
    placed = place_lessons([_ref(2, IT, f"{GROUP}:2")], GROUP, "2TN2", 1)

    assert placed[0][1] == SubgroupMark(2, "2TN2/2", False)


def test_the_own_subgroup_hides_the_other_lesson_of_the_same_subject() -> None:
    lessons = [_ref(1, ENGLISH, f"{GROUP}:2"), _ref(1, ENGLISH, f"{GROUP}:1")]

    placed = place_lessons(lessons, GROUP, "2TN2", 1)

    assert _summary(placed) == [(1, 1, True)]


def test_a_different_subject_of_the_other_subgroup_stays_visible() -> None:
    lessons = [_ref(1, ENGLISH, f"{GROUP}:1"), _ref(1, IT, f"{GROUP}:2")]

    placed = place_lessons(lessons, GROUP, "2TN2", 1)

    assert _summary(placed) == [(1, 1, True), (1, 2, False)]


def test_without_a_subgroup_every_lesson_is_own() -> None:
    lessons = [_ref(1, ENGLISH, f"{GROUP}:1"), _ref(1, ENGLISH, f"{GROUP}:2")]

    placed = place_lessons(lessons, GROUP, "2TN2", None)

    assert _summary(placed) == [(1, 1, True), (1, 2, True)]

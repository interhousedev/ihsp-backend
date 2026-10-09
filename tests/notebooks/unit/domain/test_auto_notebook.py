"""NB-AUTO: which lesson materials an auto notebook keeps, and in which order."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.modules.notebooks.domain.auto_notebook import (
    AutoCandidate,
    lesson_ref_key,
    rank_candidates,
    sync_is_stale,
)
from app.shared.ids import new_id

LESSON = new_id()


def candidate(
    role: str = "material", *, own: bool = False, day: int = 1, link: UUID | None = None
) -> AutoCandidate:
    """A resource of a lesson on October `day`."""
    return AutoCandidate(
        link_id=link or new_id(),
        lesson_id=LESSON,
        lesson_date=date(2026, 10, day),
        role=role,
        own=own,
    )


def test_ref_key_is_the_duplicate_key_of_a_lesson_source() -> None:
    """NB-AUTO: the key matches the one the lesson reader stores."""
    link = new_id()

    assert candidate(link=link).ref_key == lesson_ref_key(link) == f"lesson:{link}"


def test_classmates_files_are_left_out_unless_switched_on() -> None:
    """NB-AUTO: "Include classmates' files" is off by default."""
    material = candidate("material")
    mine = candidate("attachment", own=True)
    theirs = candidate("attachment", own=False)
    wanted = [material, mine, theirs]

    off = rank_candidates(wanted, include_classmates=False, excluded=())
    on = rank_candidates(wanted, include_classmates=True, excluded=())

    assert off == [material, mine]
    assert on == [material, mine, theirs]
    assert theirs.from_classmates and not mine.from_classmates


def test_teacher_materials_come_first_then_own_files_then_classmates() -> None:
    """NB-AUTO: when the notebook is full the least important files are the ones cut."""
    theirs = candidate("attachment", day=20)
    mine = candidate("attachment", own=True, day=10)
    material = candidate("material", day=1)

    ranked = rank_candidates(
        [theirs, mine, material], include_classmates=True, excluded=()
    )

    assert ranked == [material, mine, theirs]


def test_newest_lesson_first_within_a_group() -> None:
    """NB-AUTO: recent lessons matter most to a student."""
    old, new, mid = candidate(day=1), candidate(day=9), candidate(day=5)

    ranked = rank_candidates([old, new, mid], include_classmates=False, excluded=())

    assert ranked == [new, mid, old]


def test_excluded_resources_stay_out_for_every_sync() -> None:
    """NB-AUTO: an excluded material is never wanted again, whoever attached it."""
    keep, drop = candidate(), candidate("attachment", own=True)

    ranked = rank_candidates(
        [keep, drop], include_classmates=True, excluded={drop.ref_key}
    )

    assert ranked == [keep]


def test_a_resource_listed_twice_is_wanted_once() -> None:
    """NB-AUTO: two lessons never turn one link into two sources."""
    one = candidate()

    assert rank_candidates([one, one], include_classmates=False, excluded=()) == [one]


def test_a_sync_is_stale_after_ten_minutes_or_when_it_never_ran() -> None:
    """NB-AUTO: opening a notebook re-syncs it only when the last sync is old."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    assert sync_is_stale(None, now)
    assert sync_is_stale(now - timedelta(minutes=10), now)
    assert not sync_is_stale(now - timedelta(minutes=9), now)

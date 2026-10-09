"""Editing a control: audience, text cleaning and the patch."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.assessments import edit
from app.modules.academic.domain.assessments.errors import InvalidAssessmentError
from tests.academic.assessments.factories import (
    GROUP,
    OTHER_GROUP,
    PHYSICS,
    make_assessment,
    standard_term,
)

import pytest

D = dt.date.fromisoformat


def test_audience_keys_are_sorted_and_unique() -> None:
    """The same group twice is one key."""
    got = edit.normalize_audience([(GROUP, 1), (OTHER_GROUP, None), (GROUP, 1)])

    assert got == tuple(sorted([f"{GROUP}:1", str(OTHER_GROUP)]))


def test_a_whole_group_absorbs_its_subgroups() -> None:
    """[group, group:1] means the whole group."""
    got = edit.normalize_audience([(GROUP, 1), (GROUP, None), (GROUP, 2)])

    assert got == (str(GROUP),)


@pytest.mark.parametrize("pairs", [[], [(GROUP, None)] * 21])
def test_an_empty_or_huge_audience_is_refused(
    pairs: list[tuple[UUID, int | None]],
) -> None:
    """A control needs at least one group, and not an unbounded number."""
    with pytest.raises(InvalidAssessmentError):
        edit.normalize_audience(pairs)


def test_text_is_trimmed_and_blank_becomes_none() -> None:
    """Free text is cleaned; too long text is refused."""
    assert edit.clean_title("  Mid  ") == "Mid"
    assert edit.clean_optional("  ", "note", 10) is None
    assert edit.clean_optional(None, "note", 10) is None
    assert edit.clean_optional(" ok ", "note", 10) == "ok"
    with pytest.raises(InvalidAssessmentError):
        edit.clean_title("x" * (edit.TITLE_MAX + 1))
    with pytest.raises(InvalidAssessmentError):
        edit.clean_optional("x" * 11, "note", 10)


def test_the_start_time_must_fall_on_the_day_in_tashkent() -> None:
    """09:00 Tashkent on the 21st is 04:00 UTC the same day; 20:00 UTC is the 22nd."""
    edit.check_starts_at(D("2026-10-21"), None)
    edit.check_starts_at(
        D("2026-10-21"), dt.datetime(2026, 10, 21, 4, 0, tzinfo=dt.UTC)
    )
    with pytest.raises(InvalidAssessmentError):
        edit.check_starts_at(
            D("2026-10-21"), dt.datetime(2026, 10, 21, 20, 0, tzinfo=dt.UTC)
        )


@pytest.mark.parametrize(
    ("kind", "given", "ok"),
    [
        ("midterm", "midterm_1", True),
        ("midterm", "midterm_2", True),
        ("final", "final", True),
        ("final", "midterm_1", False),
        ("midterm", "final", False),
        ("other", "final", False),
    ],
)
def test_a_named_control_week_must_match_the_kind(
    kind: str, given: str, ok: bool
) -> None:
    """A midterm cannot be the final week."""
    if ok:
        got = edit.resolve_control(
            kind, D("2026-10-21"), [], given  # type: ignore[arg-type]
        )
        assert got == given
    else:
        with pytest.raises(InvalidAssessmentError):
            edit.resolve_control(
                kind, D("2026-10-21"), [], given  # type: ignore[arg-type]
            )


def test_an_unnamed_control_week_is_inferred_from_kind_and_date() -> None:
    """No control given: the week the date falls in."""
    terms = [standard_term()]

    assert edit.resolve_control("midterm", D("2026-11-24"), terms, None) == "midterm_2"
    assert edit.resolve_control("other", D("2026-11-24"), terms, None) is None


def test_an_untouched_patch_changes_nothing() -> None:
    """Every field left unset stays."""
    current = make_assessment(title="Algebra", room="204", note="Bring a ruler")

    assert edit.apply_patch(current, edit.AssessmentPatch()) == current


def test_a_patch_changes_only_the_sent_fields() -> None:
    """Title and room change; the rest stays; null clears the optional ones."""
    current = make_assessment(title="Algebra", room="204", note="Bring a ruler")

    got = edit.apply_patch(
        current, edit.AssessmentPatch(title=" Geometry ", room="305", note=None)
    )

    assert (got.title, got.room, got.note) == ("Geometry", "305", None)
    assert (got.subject_id, got.date, got.audience) == (
        current.subject_id,
        current.date,
        current.audience,
    )


def test_a_patch_can_move_the_subject_and_the_audience() -> None:
    """Subject and audience are editable (the use case checks the teacher again)."""
    current = make_assessment()

    got = edit.apply_patch(
        current,
        edit.AssessmentPatch(subject_id=PHYSICS, audience=[(OTHER_GROUP, 2)]),
    )

    assert got.subject_id == PHYSICS
    assert got.audience == (f"{OTHER_GROUP}:2",)


def test_editing_a_tentative_control_confirms_it() -> None:
    """Whoever fixes the date vouches for it."""
    tentative = make_assessment(status="tentative", source="emis")

    got = edit.apply_patch(tentative, edit.AssessmentPatch(room="204"))

    assert (got.status, got.source) == ("planned", "emis")


def test_a_patch_that_changes_nothing_keeps_a_tentative_control_tentative() -> None:
    """Sending the same values is not a confirmation."""
    tentative = make_assessment(status="tentative", room="204")

    got = edit.apply_patch(tentative, edit.AssessmentPatch(room="204"))

    assert got.status == "tentative"


def test_the_status_can_confirm_or_dismiss() -> None:
    """planned confirms as it is; cancelled dismisses."""
    tentative = make_assessment(status="tentative")

    assert (
        edit.apply_patch(tentative, edit.AssessmentPatch(status="planned")).status
        == "planned"
    )
    assert (
        edit.apply_patch(tentative, edit.AssessmentPatch(status="cancelled")).status
        == "cancelled"
    )


def test_moving_the_date_re_infers_the_control_week() -> None:
    """A midterm moved into the second week becomes midterm 2."""
    current = make_assessment(control="midterm_1")

    moved = edit.apply_patch(
        current, edit.AssessmentPatch(date=D("2026-11-24")), [standard_term()]
    )
    same_day = edit.apply_patch(
        current, edit.AssessmentPatch(room="1"), [standard_term()]
    )

    assert moved.control == "midterm_2"
    assert same_day.control == "midterm_1"


def test_a_named_week_wins_over_the_date() -> None:
    """The teacher says "this is midterm 2" although the date is in week 1."""
    current = make_assessment(control=None)

    got = edit.apply_patch(
        current, edit.AssessmentPatch(control="midterm_2"), [standard_term()]
    )

    assert got.control == "midterm_2"
    assert edit.apply_patch(got, edit.AssessmentPatch(control=None)).control is None


def test_a_patch_with_a_bad_time_is_refused() -> None:
    """The start time is checked against the (new) date."""
    current = make_assessment(date=D("2026-10-21"))

    with pytest.raises(InvalidAssessmentError):
        edit.apply_patch(
            current,
            edit.AssessmentPatch(starts_at=dt.datetime(2026, 10, 25, 4, tzinfo=dt.UTC)),
        )


def test_moving_the_date_moves_the_start_time_to_the_new_day() -> None:
    """09:00 Tashkent on the 21st becomes 09:00 on the 24th unless a time is sent."""
    current = make_assessment(
        date=D("2026-10-21"),
        starts_at=dt.datetime(2026, 10, 21, 4, 0, tzinfo=dt.UTC),
    )

    moved = edit.apply_patch(current, edit.AssessmentPatch(date=D("2026-10-24")))
    explicit = edit.apply_patch(
        current,
        edit.AssessmentPatch(
            date=D("2026-10-24"),
            starts_at=dt.datetime(2026, 10, 24, 6, 30, tzinfo=dt.UTC),
        ),
    )
    cleared = edit.apply_patch(
        current, edit.AssessmentPatch(date=D("2026-10-24"), starts_at=None)
    )

    assert moved.starts_at == dt.datetime(2026, 10, 24, 4, 0, tzinfo=dt.UTC)
    assert explicit.starts_at == dt.datetime(2026, 10, 24, 6, 30, tzinfo=dt.UTC)
    assert cleared.starts_at is None
    assert (
        edit.apply_patch(
            make_assessment(date=D("2026-10-21")),
            edit.AssessmentPatch(date=D("2026-10-24")),
        ).starts_at
        is None
    )

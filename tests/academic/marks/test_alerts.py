"""Notification drafts built from a sync (BOT-11 to BOT-14, ACA-22)."""

import datetime as dt
from decimal import Decimal
from uuid import UUID

from app.modules.academic.domain.marks.alerts import (
    AddedMark,
    GpaChange,
    SubjectChange,
    build_alerts,
)
from app.modules.academic.domain.marks.diff import MarkKey
from app.modules.academic.domain.marks.records import ResultSnapshot
from app.shared.contracts.emis import EmisMarkType
from app.shared.contracts.identity import UserPreferences
from app.shared.notifications import NotificationDraft, NotificationType

USER = UUID(int=7)
RUN = UUID(int=9)
PHYSICS = UUID(int=21)
MATH = UUID(int=22)
DAY = dt.date(2026, 10, 6)


def _mark(
    subject: UUID, name: str, value: int, kind: EmisMarkType = EmisMarkType.LESSON
) -> AddedMark:
    return AddedMark(subject, name, 3, MarkKey(kind, DAY, value, 1))


def _snap(
    value: str | None,
    lesson: str | None = None,
    midterm: str | None = None,
    final: str | None = None,
) -> ResultSnapshot:
    def dec(x: str | None) -> Decimal | None:
        return None if x is None else Decimal(x)

    return ResultSnapshot(dec(value), dec(lesson), dec(midterm), dec(final))


def _build(
    prefs: UserPreferences,
    added: list[AddedMark] | None = None,
    changes: list[SubjectChange] | None = None,
    gpa: list[GpaChange] | None = None,
) -> list[NotificationDraft]:
    return build_alerts(
        user_id=USER,
        run_token=RUN,
        prefs=prefs,
        added=added or [],
        subject_changes=changes or [],
        gpa_changes=gpa or [],
    )


def test_one_marks_notification_per_run_with_semester_mark_changes() -> None:
    """All new marks go into one `marks` draft with the changed semester marks."""
    added = [_mark(PHYSICS, "Physics", 3, EmisMarkType.MIDTERM), _mark(MATH, "Math", 5)]
    change = SubjectChange(
        PHYSICS, "Physics", 3, _snap("4.21", "4.21"), _snap("3.95", "3.95")
    )
    drafts = _build(UserPreferences(alerts_drops=False), added, [change])
    assert [d.type for d in drafts] == [NotificationType.MARKS]
    draft = drafts[0]
    assert draft.dedupe_key == f"marks:{RUN}:{USER}"
    assert [m["subject_name"] for m in draft.payload["marks"]] == ["Math", "Physics"]
    assert draft.payload["result_changes"] == [
        {
            "subject_id": str(PHYSICS),
            "subject_name": "Physics",
            "old": 4.21,
            "new": 3.95,
        }
    ]


def test_marks_settings_filter_types_values_and_subjects() -> None:
    """BOT-13: only the chosen types, values and subjects are announced."""
    added = [
        _mark(PHYSICS, "Physics", 3, EmisMarkType.MIDTERM),
        _mark(MATH, "Math", 5),
        _mark(MATH, "Math", 2),
    ]
    prefs = UserPreferences(
        marks_types=["lesson"], marks_values=[5, 4], marks_subject_ids=[MATH]
    )
    [draft] = _build(prefs, added)
    assert [(m["subject_name"], m["value"]) for m in draft.payload["marks"]] == [
        ("Math", 5)
    ]


def test_no_marks_notification_when_disabled_or_nothing_matches() -> None:
    """UF-BOT-04 1a: nothing matches the settings, nothing is sent."""
    added = [_mark(MATH, "Math", 5)]
    assert _build(UserPreferences(marks_enabled=False), added) == []
    assert _build(UserPreferences(marks_values=[2]), added) == []


def test_gpa_and_subject_drops_are_announced() -> None:
    """A fall of the GPA or of a semester mark creates `result_drop` drafts."""
    change = SubjectChange(
        MATH, "Math", 3, _snap("4.50", "4.50"), _snap("4.00", "4.00")
    )
    drafts = _build(
        UserPreferences(),
        None,
        [change],
        [GpaChange(3, Decimal("4.62"), Decimal("4.55"))],
    )
    drops = [d for d in drafts if d.type == NotificationType.RESULT_DROP]
    assert {d.payload["scope"] for d in drops} == {"gpa", "subject"}
    gpa = next(d for d in drops if d.payload["scope"] == "gpa")
    assert gpa.payload == {"scope": "gpa", "semester": 3, "old": 4.62, "new": 4.55}
    assert gpa.dedupe_key == f"drop:{USER}:gpa:3:4.55"


def test_drops_can_be_switched_off() -> None:
    """alerts_drops=False sends no drop."""
    gpa = GpaChange(3, Decimal("4.62"), Decimal("4.55"))
    assert _build(UserPreferences(alerts_drops=False), None, None, [gpa]) == []


def test_no_drop_when_the_formula_switched() -> None:
    """ACA-22: the final appears and the mark falls only because of the new formula."""
    before = _snap("4.50", "4.50", "3.00", None)
    after = _snap("4.17", "4.50", "3.00", "5.00")
    change = SubjectChange(MATH, "Math", 3, before, after)
    assert _build(UserPreferences(), None, [change]) == []
    same_formula = SubjectChange(
        MATH,
        "Math",
        3,
        _snap("4.50", "4.50", "3.00", "5.00"),
        _snap("4.00", "4.00", "3.00", "5.00"),
    )
    assert len(_build(UserPreferences(), None, [same_formula])) == 1


def test_threshold_alerts_fire_on_crossing_down_only() -> None:
    """result_below fires once when a value goes under the limit, not while it stays."""
    prefs = UserPreferences(
        alerts_drops=False,
        alerts_gpa_below=4.0,
        alerts_semester_mark_below=4.0,
        alerts_mark_below=3,
    )
    crossing = SubjectChange(MATH, "Math", 3, _snap("4.20"), _snap("3.90"))
    staying = SubjectChange(PHYSICS, "Physics", 3, _snap("3.50"), _snap("3.40"))
    gpa = GpaChange(3, Decimal("4.10"), Decimal("3.95"))
    drafts = _build(prefs, [_mark(MATH, "Math", 2)], [crossing, staying], [gpa])
    below = [d for d in drafts if d.type == NotificationType.RESULT_BELOW]
    assert sorted((d.payload["scope"], d.payload["value"]) for d in below) == [
        ("gpa", 3.95),
        ("mark", 2.0),
        ("subject", 3.9),
    ]
    subject = next(d for d in below if d.payload["scope"] == "subject")
    assert subject.payload["subject_name"] == "Math"
    assert subject.payload["threshold"] == 4.0
    assert len({d.dedupe_key for d in below}) == 3


def test_dedupe_keys_carry_the_user() -> None:
    """notifications.dedupe_key is unique across users, so every key names the user."""
    prefs = UserPreferences(alerts_gpa_below=5.0)
    gpa = GpaChange(3, Decimal("4.62"), Decimal("4.55"))
    drafts = _build(prefs, None, None, [gpa])
    assert drafts and all(str(USER) in d.dedupe_key for d in drafts)

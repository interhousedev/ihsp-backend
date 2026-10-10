"""The LessonItem JSON shape of the API contract."""

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.academic.domain.lesson_item import lesson_item
from app.shared.contracts.academic import LessonRef

LESSON = UUID("0192f3c4-0000-7000-8000-00000000000a")
SUBJECT = UUID("0192f3c4-0000-7000-8000-00000000000b")
ROOM = UUID("0192f3c4-0000-7000-8000-00000000000c")
GROUP = UUID("0192f3c4-0000-7000-8000-00000000000d")


def _ref(**fields: object) -> LessonRef:
    values: dict[str, object] = {
        "id": LESSON,
        "date": date(2026, 10, 6),
        "period": 2,
        "starts_at": datetime(2026, 10, 6, 4, 25, tzinfo=UTC),
        "ends_at": datetime(2026, 10, 6, 5, 10, tzinfo=UTC),
        "subject_id": SUBJECT,
        "subject_name": "Mathematics",
        "teacher_id": None,
        "room_id": ROOM,
        "room_slug": "102",
        "room_name": "102",
        "audience": (str(GROUP),),
        "group_names": ("2TN2",),
        "status": "scheduled",
        "topic": None,
        "homework_text": None,
        "homework_due_date": None,
    }
    return LessonRef(**{**values, **fields})  # type: ignore[arg-type]


def _item(ref: LessonRef, **fields: object) -> dict[str, object]:
    values: dict[str, object] = {
        "teacher": None,
        "subject_short": "Math",
        "audience": [{"group_id": str(GROUP), "group_name": "2TN2", "subgroup": None}],
        "attendance_submitted": False,
        "has_homework": False,
        "is_overridden": False,
        "changes": None,
    }
    return lesson_item(ref, **{**values, **fields})  # type: ignore[arg-type]


def test_lesson_item_has_exactly_the_contract_fields() -> None:
    item = _item(_ref())

    assert set(item) == {
        "id",
        "date",
        "period",
        "starts_at",
        "ends_at",
        "subject",
        "teacher",
        "room",
        "audience",
        "status",
        "is_overridden",
        "changes",
        "topic",
        "kind",
        "topic_source",
        "has_homework",
        "attendance_submitted",
        "absent_count",
    }


def test_ids_dates_and_times_are_strings() -> None:
    item = _item(_ref())

    assert item["id"] == str(LESSON)
    assert item["date"] == "2026-10-06"
    assert item["starts_at"] == "2026-10-06T04:25:00+00:00"


def test_subject_and_room_refs() -> None:
    item = _item(_ref())

    assert item["subject"] == {
        "id": str(SUBJECT),
        "name": "Mathematics",
        "short_name": "Math",
    }
    assert item["room"] == {"id": str(ROOM), "slug": "102", "name": "102"}


def test_lesson_without_a_room_has_null_room() -> None:
    item = _item(_ref(room_id=None, room_slug=None, room_name=None))

    assert item["room"] is None


def test_missing_short_name_falls_back_to_the_subject_name() -> None:
    item = _item(_ref(), subject_short=None)

    assert item["subject"] == {
        "id": str(SUBJECT),
        "name": "Mathematics",
        "short_name": "Mathematics",
    }


def test_teacher_and_changes_are_passed_through() -> None:
    teacher = {"id": str(GROUP), "first_name": "Aleksey", "last_name": "Brastilov"}
    changes = {"room": ["204", "310"]}

    item = _item(_ref(), teacher=teacher, changes=changes, is_overridden=True)

    assert item["teacher"] == teacher
    assert item["changes"] == changes
    assert item["is_overridden"] is True


def test_kind_and_topic_source_come_from_the_lesson() -> None:
    """EMIS labels: the exam kind, and who wrote the topic."""
    ref = _ref(kind="midterm", topic="Jadids", topic_source="emis")

    item = _item(ref)

    assert (item["kind"], item["topic_source"]) == ("midterm", "emis")
    plain = _item(_ref())
    assert (plain["kind"], plain["topic_source"]) == ("other", None)


def test_lesson_item_carries_the_absent_count() -> None:
    assert _item(_ref())["absent_count"] is None
    assert _item(_ref(), attendance_submitted=True, absent_count=3)["absent_count"] == 3

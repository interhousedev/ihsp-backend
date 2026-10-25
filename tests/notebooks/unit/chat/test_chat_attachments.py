"""Chat attachments: a lesson or one of its materials as a pinned text."""

from typing import Any
from uuid import UUID, uuid4

from app.interfaces.http.v1.me_classwork.schemas import StudentLessonResponse
from app.interfaces.http.v1.notebooks.handlers.attachments import (
    attachment_anchor,
    lesson_context,
)
from app.interfaces.http.v1.notebooks.schemas_chat import ChatAttachment
from app.modules.notebooks.domain.entities import AnchorPassages, AnchorText
from app.shared.actor import Actor, Role

import pytest
from pydantic import ValidationError

LESSON_ID = uuid4()
SLIDES_ID = uuid4()
WORKSHEET_ID = uuid4()


def resource(link_id: UUID, title: str, hidden: bool = False) -> dict[str, Any]:
    """A material of the lesson as `StudentLesson` lists it."""
    return {
        "link_id": link_id,
        "lesson_id": LESSON_ID,
        "role": "material",
        "kind": "file",
        "short_url": "https://s.test/x",
        "title": title,
        "author": {"id": uuid4(), "first_name": "A", "last_name": "B"},
        "hidden": hidden,
        "file": None,
        "created_at": None,
    }


def student_lesson(homework: str | None = "Read pages 10-12") -> dict[str, Any]:
    """The `StudentLesson` JSON of a biology lesson."""
    subject = {"id": uuid4(), "name": "Biology", "short_name": "Bio"}
    return {
        "lesson": {
            "id": LESSON_ID,
            "date": "2026-10-12",
            "period": 2,
            "starts_at": "2026-10-12T09:00:00+05:00",
            "ends_at": "2026-10-12T09:45:00+05:00",
            "subject": subject,
            "teacher": None,
            "room": None,
            "audience": [],
            "status": "scheduled",
            "is_overridden": False,
            "changes": None,
            "topic": "Photosynthesis",
            "has_homework": homework is not None,
            "attendance_submitted": False,
        },
        "materials": [
            resource(SLIDES_ID, "Slides"),
            resource(WORKSHEET_ID, "Worksheet"),
            resource(uuid4(), "Draft", hidden=True),
        ],
        "attachments": [],
        "homework": (
            {
                "lesson_id": LESSON_ID,
                "subject": subject,
                "teacher": None,
                "text": homework,
                "due_date": None,
                "given_on": "2026-10-12",
                "days_overdue": 0,
                "updated": False,
                "done_at": None,
                "note": None,
            }
            if homework
            else None
        ),
        "my_mark": [],
        "my_attendance": "present",
        "can_attach": True,
    }


def actor(*roles: Role) -> Actor:
    """A signed-in user with the roles."""
    return Actor(user_id=uuid4(), roles=frozenset(roles))


class Reader:
    """A fake `StudentLesson.execute` that records the lessons it was asked for."""

    def __init__(self) -> None:
        self.asked: list[UUID] = []

    async def __call__(self, lesson_id: UUID, who: Actor) -> dict[str, Any]:
        self.asked.append(lesson_id)
        return student_lesson()


def test_a_lesson_gives_subject_date_topic_materials_and_homework() -> None:
    text = lesson_context(StudentLessonResponse.model_validate(student_lesson()))

    assert "Biology" in text and "2026-10-12" in text
    assert "Topic: Photosynthesis" in text
    assert "Material: Slides" in text and "Material: Worksheet" in text
    assert "Draft" not in text
    assert "Homework: Read pages 10-12" in text


def test_a_material_keeps_only_that_material() -> None:
    lesson = StudentLessonResponse.model_validate(student_lesson())

    text = lesson_context(lesson, SLIDES_ID)

    assert "Material: Slides" in text
    assert "Worksheet" not in text and "Homework" not in text


async def test_attachments_become_a_pinned_text() -> None:
    reader = Reader()
    attachments = [ChatAttachment(kind="lesson", id=LESSON_ID)]

    anchor = await attachment_anchor(attachments, None, actor(Role.STUDENT), reader)

    assert isinstance(anchor, AnchorText)
    assert "Topic: Photosynthesis" in anchor.text
    assert reader.asked == [LESSON_ID]


async def test_a_selected_text_stays_in_front_of_the_lesson() -> None:
    attachments = [ChatAttachment(kind="lesson", id=LESSON_ID)]
    selected = AnchorText(text="chlorophyll")

    anchor = await attachment_anchor(
        attachments, selected, actor(Role.STUDENT), Reader()
    )

    assert isinstance(anchor, AnchorText)
    assert anchor.text.startswith("chlorophyll")
    assert len(anchor.text) <= 4000


async def test_a_material_reads_its_lesson() -> None:
    reader = Reader()
    attachments = [ChatAttachment(kind="material", id=SLIDES_ID, lesson_id=LESSON_ID)]

    anchor = await attachment_anchor(attachments, None, actor(Role.STUDENT), reader)

    assert reader.asked == [LESSON_ID]
    assert isinstance(anchor, AnchorText) and "Worksheet" not in anchor.text


@pytest.mark.parametrize(
    "who, pinned",
    [
        pytest.param(actor(Role.TEACHER), None, id="not-a-student"),
        pytest.param(actor(Role.STUDENT), AnchorPassages(ids=[uuid4()]), id="passages"),
    ],
)
async def test_attachments_are_left_out(
    who: Actor, pinned: AnchorPassages | None
) -> None:
    reader = Reader()
    attachments = [ChatAttachment(kind="lesson", id=LESSON_ID)]

    anchor = await attachment_anchor(attachments, pinned, who, reader)

    assert anchor is pinned
    assert reader.asked == []


def test_a_material_without_its_lesson_is_invalid() -> None:
    with pytest.raises(ValidationError):
        ChatAttachment(kind="material", id=SLIDES_ID)

"""Chat attachments: a lesson, or one of its materials, the question is about.

The student app attaches a lesson to a question; its subject, date, topic,
materials and homework reach the model as a pinned text (`AnchorText`), after a
text the student selected. Pinned passages stay as they are; teachers' questions
keep no attachments (the lesson page is a student's view).
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.me_classwork.schemas import StudentLessonResponse
from app.interfaces.http.v1.notebooks.schemas_chat import ChatAttachment
from app.modules.notebooks.domain.entities import AnchorPassages, AnchorText
from app.shared.actor import Actor, Role

from fastapi import Depends

ANCHOR_MAX_CHARS = 4000

LessonReader = Callable[[UUID, Actor], Awaitable[dict[str, Any]]]


def get_lesson_reader(
    container: Annotated[Container, Depends(get_container)],
) -> LessonReader:
    """The student's lesson page (`GET /v1/me/lessons/{id}`); 404 if not theirs.

    Resolved on use: a question without attachments never touches the academic module.
    """

    async def read(lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        reader: LessonReader = container.academic.classwork.student_lesson.execute
        return await reader(lesson_id, actor)

    return read


LessonReaderDep = Annotated[LessonReader, Depends(get_lesson_reader)]


def lesson_context(lesson: StudentLessonResponse, link_id: UUID | None = None) -> str:
    """The lesson as lines for the model; with `link_id`, only that material."""
    item = lesson.lesson
    lines = [f"Lesson: {item.subject.name}, {item.date.isoformat()}"]
    if item.topic:
        lines.append(f"Topic: {item.topic}")
    for material in lesson.materials:
        if material.hidden or (link_id is not None and material.link_id != link_id):
            continue
        lines.append(f"Material: {material.title}")
    if lesson.homework is not None and link_id is None:
        lines.append(f"Homework: {lesson.homework.text}")
    return "\n".join(lines)


async def attachment_anchor(
    attachments: Sequence[ChatAttachment],
    anchor: AnchorPassages | AnchorText | None,
    actor: Actor,
    read_lesson: LessonReader,
) -> AnchorPassages | AnchorText | None:
    """The anchor of the question with the attached lessons added as text."""
    if not attachments or not actor.has(Role.STUDENT):
        return anchor
    if isinstance(anchor, AnchorPassages):
        return anchor
    parts = [anchor.text] if anchor is not None else []
    for attachment in attachments:
        material = attachment.kind == "material"
        lesson_id = attachment.lesson_id if material else attachment.id
        data = await read_lesson(lesson_id or attachment.id, actor)
        lesson = StudentLessonResponse.model_validate(data)
        parts.append(lesson_context(lesson, attachment.id if material else None))
    return AnchorText(text="\n\n".join(parts)[:ANCHOR_MAX_CHARS])

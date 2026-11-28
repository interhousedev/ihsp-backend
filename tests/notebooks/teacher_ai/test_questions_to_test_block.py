"""Generated questions -> LMS `TestBlock` (spec 3.2a, "Output -> LMS").

The implementation must provide:
- `app.modules.notebooks.application.course_convert.questions_to_test_block(
  questions: Sequence[QuestionItem]) -> dict` (pure, next to `quiz_to_blocks`, built on
  the shared `build_test_block` contract; NOT a second converter in `lms`). A question
  with options is `single` choice and exactly ONE option must equal `answer` (trimmed,
  case-insensitive): zero or several matches, or duplicate options, raise
  `BlockInputError` (a ValueError); the explanation is the question's `explanation`.
  Without options it is a `text` question with `answer.accepted == [answer]`.
  An empty list raises `BlockInputError`.
- `app.modules.lms.application.authoring.add_blocks_from_questions.
  AddBlocksFromQuestions(steps, append).execute(actor, course_id, step_id, questions,
  position)`: `steps.course_of(step_id) -> UUID | None` must equal `course_id`, else
  NotFoundError (a deleted step has no course); then `append.execute(actor, step_id,
  block, position=position)` (the real `AppendBlock`, extended with `position`, which
  enforces course `edit`: read-only staff, unrelated teachers and students are
  refused and nothing is written).
- Route `POST /v1/lms/courses/{cid}/steps/{sid}/blocks:from-questions` with body
  `{"questions": [{question, answer, options, explanation}], "position": int | null}`;
  201 and the new block; a student 403; an empty list 422. Router:
  `app.interfaces.http.v1.lms_authoring.ROUTERS` with `container.lms_authoring`
  replaced by a recording fake exposing `add_blocks_from_questions(actor, course_id,
  step_id, questions, position)`.
"""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.add_blocks_from_questions import (
    AddBlocksFromQuestions,
)
from app.modules.notebooks.application.course_convert import questions_to_test_block
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.lms_blocks import BlockInputError
from app.shared.contracts.teacher_ai import QuestionItem
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.factories import make_actor as build_actor

import pytest


def test_choice_question_marks_the_answer_correct() -> None:
    """The option equal to the answer is the only correct one; the explanation stays."""
    block = questions_to_test_block(
        [QuestionItem("2+2?", "4", options=("3", "4", "5"), explanation="sum")]
    )

    assert block["type"] == "test"
    (question,) = block["questions"]
    assert question["type"] == "single" and question["explanation"] == "sum"
    assert [(o["text"], bool(o["correct"])) for o in question["options"]] == [
        ("3", False),
        ("4", True),
        ("5", False),
    ]


def test_open_question_becomes_a_short_answer_with_the_accepted_answer() -> None:
    block = questions_to_test_block(
        [QuestionItem("Capital of Uzbekistan?", "Tashkent", explanation="since 1930")]
    )

    (question,) = block["questions"]
    assert question["type"] == "text"
    assert question["answer"]["accepted"] == ["Tashkent"]
    assert question["explanation"] == "since 1930"


@pytest.mark.parametrize(
    "item",
    [
        QuestionItem("a?", "9", ("1", "2")),  # no option matches the answer
        QuestionItem("a?", "1", ("1", " 1 ", "2")),  # the answer matches twice
        QuestionItem("a?", "1", ("1", "1")),  # duplicate options
    ],
)
def test_ambiguous_choice_answers_are_refused(item: QuestionItem) -> None:
    with pytest.raises(BlockInputError):
        questions_to_test_block([item])


def test_order_is_kept_and_empty_input_is_refused() -> None:
    block = questions_to_test_block(
        [QuestionItem("a?", "1", ("1", "2")), QuestionItem("b?", "2", ("1", "2"))]
    )
    assert [q["prompt"] for q in block["questions"]] == ["a?", "b?"]
    with pytest.raises(BlockInputError):
        questions_to_test_block([])


COURSE, STEP = new_id(), new_id()


class Steps:
    """`course_of`: step -> its course; a deleted step is absent."""

    def __init__(self, mapping: dict[UUID, UUID]) -> None:
        self.mapping = mapping

    async def course_of(self, step_id: UUID) -> UUID | None:
        return self.mapping.get(step_id)


class Append:
    """The real `AppendBlock` enforces `edit`; this fake knows who may edit."""

    def __init__(self, editors: set[UUID]) -> None:
        self.editors = editors
        self.written: list[tuple[UUID, dict[str, Any], int | None]] = []

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block: dict[str, Any],
        *,
        position: int | None = None,
    ) -> dict[str, Any]:
        if actor.user_id not in self.editors:
            raise ForbiddenError()
        self.written.append((step_id, block, position))
        return {"block_id": "b1"}


QUESTIONS = [QuestionItem("2+2?", "4", ("3", "4"))]


def _use_case(editor: Actor) -> tuple[AddBlocksFromQuestions, Append]:
    append = Append({editor.user_id})
    return AddBlocksFromQuestions(Steps({STEP: COURSE}), append), append


async def test_course_editor_adds_the_block_at_the_position() -> None:
    editor = build_actor(Role.TEACHER)
    use_case, append = _use_case(editor)

    await use_case.execute(editor, COURSE, STEP, QUESTIONS, 2)

    ((step, block, position),) = append.written
    assert (step, position, block["type"]) == (STEP, 2, "test")


async def test_unrelated_teacher_and_read_only_staff_write_nothing() -> None:
    use_case, append = _use_case(build_actor(Role.TEACHER))

    for outsider in (build_actor(Role.TEACHER), build_actor(Role.STUDENT)):
        with pytest.raises(ForbiddenError):
            await use_case.execute(outsider, COURSE, STEP, QUESTIONS, None)
    assert append.written == []


async def test_step_of_another_course_or_deleted_step_is_not_found() -> None:
    editor = build_actor(Role.TEACHER)
    use_case, append = _use_case(editor)

    with pytest.raises(NotFoundError):
        await use_case.execute(
            editor, new_id(), STEP, QUESTIONS, None
        )  # mismatched course
    with pytest.raises(NotFoundError):
        await use_case.execute(
            editor, COURSE, new_id(), QUESTIONS, None
        )  # deleted step
    assert append.written == []


class RecordingAuthoring:
    """Fake of the authoring facade behind the route."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def add_blocks_from_questions(self, *args: Any) -> dict[str, Any]:
        self.calls.append(args)
        return {"id": "b1", "type": "test", "questions": []}


async def test_route_adds_a_test_block_for_course_staff(
    http_client: HttpClientFactory, make_actor: Any
) -> None:
    """A teacher gets 201; a student 403 and nothing is written."""
    from app.interfaces.http.dependencies import get_actor
    from app.interfaces.http.v1.lms_authoring import ROUTERS

    current: dict[str, Actor] = {"actor": make_actor(Role.TEACHER)}
    fake = RecordingAuthoring()
    api = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, lms_authoring=fake
    )
    url = f"/v1/lms/courses/{new_id()}/steps/{new_id()}/blocks:from-questions"
    body = {"questions": [{"question": "q?", "answer": "a"}], "position": 0}

    ok = await api.post(url, json=body)
    empty = await api.post(url, json={"questions": []})
    current["actor"] = make_actor(Role.STUDENT)
    denied = await api.post(url, json=body)

    assert ok.status_code == 201, ok.text
    assert empty.status_code == 422
    assert denied.status_code == 403
    assert len(fake.calls) == 1

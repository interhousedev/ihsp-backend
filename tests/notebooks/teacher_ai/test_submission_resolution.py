"""The tools read a student's submission server-side, actor-scoped (spec 3.2a).

The routes only forward `submission_id`; the work itself is read here, so a teacher can
never check, or store the verdict of, a submission they do not teach.

The implementation must provide:
- `app.shared.contracts.teacher_ai.SubmissionReader` protocol: `async read(actor,
  submission_id) -> SubmissionWork(assignment, student_work, subject_id, group_id |
  None, lesson_id)`; implemented over `academic` with the same lesson authorization as
  `ListHomeworkSubmissions` (the teacher teaches that lesson's group; admin passes);
  raises NotFoundError for an unknown OR foreign submission (no existence leak).
  The homework submission record, the teacher's submissions list response and
  OpenAPI carry the submission `id` (today they do not), so the checker UI has
  something to send.
- `CheckWorkArgs` and `CheckAuthorshipArgs` gain `submission_id: UUID | None = None`;
  `CheckWorkArgs` also gains `subject_id`, `group_id` (see the sink tests).
- `app.modules.notebooks.application.teaching.submissions.
  SubmissionResolvingTeacherAi(inner, reader)` implements `TeacherAiTools`; it is the
  OUTERMOST wrapper (over `SinkingTeacherAi`): with a `submission_id` it reads the
  work first, and calls `inner` with `assignment`/`student_work` (resp. `text`)
  filled in from the submission and `subject_id`/`group_id` taken from it (explicit
  values from the caller are kept); everything else is passed through.
"""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from app.modules.notebooks.application.teaching.submissions import (
    SubmissionResolvingTeacherAi,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.contracts.teacher_ai import (
    CheckAuthorshipArgs,
    CheckAuthorshipResult,
    CheckWorkArgs,
    CheckWorkResult,
    SubmissionWork,
)
from app.shared.ids import new_id
from tests.factories import make_actor

import pytest

SUBJECT, GROUP, LESSON, SUBMISSION = new_id(), new_id(), new_id(), new_id()


class Reader:
    """`SubmissionReader`: only the teacher `owner` teaches this submission."""

    def __init__(self, owner: Actor) -> None:
        self.owner, self.reads = owner, 0

    async def read(self, actor: Actor, submission_id: Any) -> Any:
        self.reads += 1
        if actor.user_id != self.owner.user_id or submission_id != SUBMISSION:
            raise NotFoundError()
        return SubmissionWork("Essay on optics", "Light bends.", SUBJECT, GROUP, LESSON)


class Inner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def check_work(self, actor: Actor, args: Any) -> Any:
        self.calls.append(("check_work", args))
        return CheckWorkResult("ok", 4.0, 5.0)

    async def check_ai_authorship(self, actor: Actor, args: Any) -> Any:
        self.calls.append(("check_ai_authorship", args))
        return CheckAuthorshipResult("uncertain", 0.4)

    async def generate_questions(self, actor: Actor, args: Any) -> Any:
        self.calls.append(("generate_questions", args))


@pytest.fixture
def rig() -> SimpleNamespace:
    teacher, inner = make_actor(Role.TEACHER), Inner()
    reader = Reader(teacher)
    return SimpleNamespace(
        teacher=teacher,
        inner=inner,
        reader=reader,
        tools=SubmissionResolvingTeacherAi(inner, reader),
    )


async def test_work_check_gets_the_submitted_text_and_its_subject(
    rig: SimpleNamespace,
) -> None:
    await rig.tools.check_work(
        rig.teacher, CheckWorkArgs("", "", max_score=5, submission_id=SUBMISSION)
    )

    ((name, args),) = rig.inner.calls
    assert name == "check_work"
    assert (args.assignment, args.student_work) == ("Essay on optics", "Light bends.")
    assert (args.subject_id, args.group_id, args.max_score) == (SUBJECT, GROUP, 5)


async def test_authorship_check_gets_the_submitted_text(rig: SimpleNamespace) -> None:
    await rig.tools.check_ai_authorship(
        rig.teacher, CheckAuthorshipArgs("", submission_id=SUBMISSION)
    )

    ((_, args),) = rig.inner.calls
    assert args.text == "Light bends."


async def test_a_foreign_or_unknown_submission_is_not_found_and_nothing_runs(
    rig: SimpleNamespace,
) -> None:
    colleague = make_actor(Role.TEACHER)

    with pytest.raises(NotFoundError):
        await rig.tools.check_work(
            colleague, CheckWorkArgs("", "", submission_id=SUBMISSION)
        )
    with pytest.raises(NotFoundError):
        await rig.tools.check_ai_authorship(
            rig.teacher, CheckAuthorshipArgs("", submission_id=new_id())
        )
    assert rig.inner.calls == []


async def test_pasted_work_does_not_touch_the_reader_and_other_calls_pass_through(
    rig: SimpleNamespace,
) -> None:
    await rig.tools.check_work(rig.teacher, CheckWorkArgs("essay", "text"))
    await rig.tools.generate_questions(rig.teacher, object())

    assert rig.reader.reads == 0
    assert [name for name, _ in rig.inner.calls] == ["check_work", "generate_questions"]


async def test_an_explicit_destination_is_kept(rig: SimpleNamespace) -> None:
    other = new_id()
    args = replace(CheckWorkArgs("", "", submission_id=SUBMISSION), subject_id=other)

    await rig.tools.check_work(rig.teacher, args)

    assert rig.inner.calls[0][1].subject_id == other

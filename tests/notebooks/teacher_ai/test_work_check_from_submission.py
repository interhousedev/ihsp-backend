"""Work check and authorship check from the homework checker (spec 3.2a).

The homework checker offers "check with AI" per submission, so the teacher no longer
pastes the work: the routes take a submission id and read the text server-side.

The implementation must provide, on `app.interfaces.http.v1.teacher_ai.ROUTERS`:
- `POST /v1/teacher/ai/work-check` body `{"submission_id": uuid, "rubric"?,
  "max_score"?}` as an alternative to `{"assignment", "student_work"}`; exactly one
  of the two forms (both or neither -> 422). The tools receive `CheckWorkArgs`
  with `submission_id` set (new field `submission_id: UUID | None = None`; then
  `assignment` and `student_work` may be empty and the tools fill them in).
- `POST /v1/teacher/ai/authorship-check` accepts `{"submission_id": uuid}` the same
  way (`CheckAuthorshipArgs.submission_id`).
- A submission the teacher does not teach -> 404 (the tools raise NotFoundError; the
  actor-scoped reading itself is tested in `test_submission_resolution.py`);
  students -> 403, as for every route here. Same MCP tools gain the argument.
- The by-submission form needs no `subject_id`: subject and group come from the
  submission (the routes' destination rule is in `test_teacher_ai_routes.py`).
"""

from collections.abc import Callable
from typing import Any

from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.ids import new_id
from tests.notebooks.teacher_ai.test_teacher_ai_routes import (  # noqa: F401
    BASE,
    RecordingTeacherAi,
    ai,
    api,
    current,
)

import pytest
from httpx import AsyncClient


async def test_work_check_by_submission_id(
    api: AsyncClient, ai: RecordingTeacherAi, current: dict[str, Actor]  # noqa: F811
) -> None:
    submission = new_id()

    response = await api.post(
        f"{BASE}/work-check", json={"submission_id": str(submission), "max_score": 5}
    )

    assert response.status_code == 200, response.text
    name, actor, args = ai.calls[0]
    assert name == "check_work" and actor == current["actor"]
    assert args.submission_id == submission and args.max_score == 5


async def test_authorship_check_by_submission_id(
    api: AsyncClient, ai: RecordingTeacherAi  # noqa: F811
) -> None:
    submission = new_id()

    response = await api.post(
        f"{BASE}/authorship-check", json={"submission_id": str(submission)}
    )

    assert response.status_code == 200, response.text
    assert ai.calls[0][2].submission_id == submission


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"submission_id": str(new_id()), "assignment": "essay", "student_work": "text"},
    ],
)
async def test_exactly_one_form_is_accepted(
    api: AsyncClient, body: dict[str, Any]  # noqa: F811
) -> None:
    response = await api.post(f"{BASE}/work-check", json=body)

    assert response.status_code == 422


async def test_students_are_refused(
    api: AsyncClient,  # noqa: F811
    current: dict[str, Actor],  # noqa: F811
    make_actor: Callable[..., Actor],  # noqa: F811
) -> None:
    current["actor"] = make_actor(Role.STUDENT)

    response = await api.post(
        f"{BASE}/work-check", json={"submission_id": str(new_id())}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/work-check", "/authorship-check"])
async def test_foreign_submission_is_a_404(
    api: AsyncClient, ai: RecordingTeacherAi, path: str  # noqa: F811
) -> None:
    ai.fail = NotFoundError()

    response = await api.post(f"{BASE}{path}", json={"submission_id": str(new_id())})

    assert response.status_code == 404

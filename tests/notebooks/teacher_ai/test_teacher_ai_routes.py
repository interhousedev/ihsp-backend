"""HTTP: /v1/teacher/ai/* over `TeacherAiTools` (spec 3.2a), role checks, MCP parity.

The implementation must provide:
- `app.interfaces.http.v1.teacher_ai.ROUTERS` (list[APIRouter]); the routes read the
  tools from `container.teacher_ai_tools` (the same object the MCP server uses).
- POST /v1/teacher/ai/{questions,handout,work-check,authorship-check,lesson-plan}
- GET/POST /v1/teacher/ai/plan-templates
- Roles: teacher and admin pass; student, parent etc. get 403 and the tools are
  never called. Domain errors map to problem+json (422 for TeacherInputError).
- Each `TeacherAiTools` method has one HTTP route and one MCP tool (parity).
- Work/authorship checks also take a `submission_id` (see
  `test_work_check_from_submission.py`).
- Destination: every generating route (questions, handout, lesson-plan, and work-check
  in its pasted-text form) REQUIRES `subject_id` (uuid; optional `group_id`), so the
  output always reaches a notebook (material sink); a missing one is 422 and the tools
  are not called. Work check by `submission_id` takes subject/group from the
  submission. The MCP tools keep `subject_id` optional (no destination = returned,
  not stored); only the web routes enforce it. Authorship check and the template
  routes have no destination (nothing is stored for them).
"""

import dataclasses
import inspect
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.teacher_ai import ROUTERS
from app.modules.notebooks.application.teaching.tools import TeacherInputError
from app.shared.actor import Actor, Role
from app.shared.contracts.teacher_ai import (
    CheckAuthorshipArgs,
    CheckAuthorshipResult,
    CheckWorkArgs,
    CheckWorkResult,
    GenerateHandoutArgs,
    GenerateHandoutResult,
    GenerateLessonPlanArgs,
    GenerateLessonPlanResult,
    GenerateQuestionsArgs,
    GenerateQuestionsResult,
    PlanTemplateResult,
    QuestionItem,
    RegisterPlanTemplateArgs,
    TeacherAiTools,
)
from app.shared.ids import new_id
from app.shared.mcp_scopes import server_tools
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

BASE = "/v1/teacher/ai"

# TeacherAiTools method -> (HTTP method, path, MCP tool name)
SURFACES = {
    "generate_questions": ("POST", "/questions", "generate_questions"),
    "generate_handout": ("POST", "/handout", "generate_handout"),
    "check_work": ("POST", "/work-check", "check_student_work"),
    "check_ai_authorship": ("POST", "/authorship-check", "check_ai_authorship"),
    "list_plan_templates": ("GET", "/plan-templates", "list_plan_templates"),
    "register_plan_template": ("POST", "/plan-templates", "register_plan_template"),
    "generate_lesson_plan": ("POST", "/lesson-plan", "generate_lesson_plan"),
}

TEMPLATE_ID = new_id()
SUBJECT = new_id()
GROUP = new_id()


class RecordingTeacherAi:
    """In-memory `TeacherAiTools`: records `(method, actor, args)`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Actor, Any]] = []
        self.fail: Exception | None = None

    def _log(self, name: str, actor: Actor, args: Any) -> None:
        self.calls.append((name, actor, args))
        if self.fail is not None:
            raise self.fail

    async def generate_questions(
        self, actor: Actor, args: GenerateQuestionsArgs
    ) -> GenerateQuestionsResult:
        self._log("generate_questions", actor, args)
        return GenerateQuestionsResult(
            (QuestionItem("2+2?", "4", options=("3", "4"), explanation="sum"),)
        )

    async def generate_handout(
        self, actor: Actor, args: GenerateHandoutArgs
    ) -> GenerateHandoutResult:
        self._log("generate_handout", actor, args)
        return GenerateHandoutResult("Optics", "# Optics")

    async def check_work(self, actor: Actor, args: CheckWorkArgs) -> CheckWorkResult:
        self._log("check_work", actor, args)
        return CheckWorkResult("ok", 4.0, 5.0, strengths=("clear",))

    async def check_ai_authorship(
        self, actor: Actor, args: CheckAuthorshipArgs
    ) -> CheckAuthorshipResult:
        self._log("check_ai_authorship", actor, args)
        return CheckAuthorshipResult("uncertain", 0.4, ("flat",), "an estimate")

    async def list_plan_templates(self, actor: Actor) -> tuple[PlanTemplateResult, ...]:
        self._log("list_plan_templates", actor, None)
        return (PlanTemplateResult(TEMPLATE_ID, "Standard"),)

    async def register_plan_template(
        self, actor: Actor, args: RegisterPlanTemplateArgs
    ) -> PlanTemplateResult:
        self._log("register_plan_template", actor, args)
        return PlanTemplateResult(TEMPLATE_ID, args.name, args.description)

    async def generate_lesson_plan(
        self, actor: Actor, args: GenerateLessonPlanArgs
    ) -> GenerateLessonPlanResult:
        self._log("generate_lesson_plan", actor, args)
        return GenerateLessonPlanResult(new_id(), "Plan", "# Plan", args.template_id)


@pytest.fixture
def ai() -> RecordingTeacherAi:
    """The tools behind the routes."""
    return RecordingTeacherAi()


@pytest.fixture
def current(make_actor: Callable[..., Actor]) -> dict[str, Actor]:
    """The caller; a teacher by default."""
    return {"actor": make_actor(Role.TEACHER)}


@pytest.fixture
async def api(
    http_client: HttpClientFactory, ai: RecordingTeacherAi, current: dict[str, Actor]
) -> AsyncClient:
    """Routes over the recording tools."""
    return await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, teacher_ai_tools=ai
    )


def _request(method: str, path: str, body: dict[str, Any]) -> tuple[str, str, dict]:
    return method, BASE + path, ({"json": body} if method == "POST" else {})


BODIES = {
    "/questions": {
        "topic": "optics",
        "count": 5,
        "question_type": "multiple_choice",
        "subject_id": str(SUBJECT),
        "group_id": str(GROUP),
    },
    "/handout": {"topic": "optics", "length": "short", "subject_id": str(SUBJECT)},
    "/work-check": {
        "assignment": "essay",
        "student_work": "text",
        "max_score": 5,
        "subject_id": str(SUBJECT),
    },
    "/authorship-check": {"text": "some text", "context": "essay"},
    "/lesson-plan": {
        "topic": "optics",
        "duration_minutes": 40,
        "subject_id": str(SUBJECT),
    },
    "/plan-templates": {"name": "Standard", "template": "1. Goal"},
}


async def test_questions_route_maps_body_to_args_and_result_to_json(
    api: AsyncClient, ai: RecordingTeacherAi, current: dict[str, Actor]
) -> None:
    """The body becomes `GenerateQuestionsArgs`; the actor is the caller."""
    response = await api.post(f"{BASE}/questions", json=BODIES["/questions"])

    assert response.status_code == 200, response.text
    name, actor, args = ai.calls[0]
    assert name == "generate_questions" and actor == current["actor"]
    assert args == GenerateQuestionsArgs(
        "optics", 5, "multiple_choice", subject_id=SUBJECT, group_id=GROUP
    )
    assert response.json()["questions"] == [
        {
            "question": "2+2?",
            "answer": "4",
            "options": ["3", "4"],
            "explanation": "sum",
        }
    ]


async def test_each_route_calls_its_method(
    api: AsyncClient, ai: RecordingTeacherAi
) -> None:
    """Every route reaches exactly its `TeacherAiTools` method."""
    expected = {
        "/questions": "generate_questions",
        "/handout": "generate_handout",
        "/work-check": "check_work",
        "/authorship-check": "check_ai_authorship",
        "/lesson-plan": "generate_lesson_plan",
        "/plan-templates": "register_plan_template",
    }
    for path, method in expected.items():
        ai.calls.clear()
        response = await api.post(BASE + path, json=BODIES[path])
        assert response.status_code in (200, 201), (path, response.text)
        assert [c[0] for c in ai.calls] == [method]

    listed = await api.get(f"{BASE}/plan-templates")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Standard"
    assert ai.calls[-1][0] == "list_plan_templates"


async def test_authorship_result_keeps_the_caveat(api: AsyncClient) -> None:
    """The estimate is shown with its caveat ("an estimate, not proof")."""
    body = (
        await api.post(f"{BASE}/authorship-check", json=BODIES["/authorship-check"])
    ).json()

    assert body["verdict"] == "uncertain"
    assert body["ai_likelihood"] == 0.4
    assert body["caveat"] == "an estimate"


async def test_lesson_plan_accepts_ids(
    api: AsyncClient, ai: RecordingTeacherAi
) -> None:
    """`lesson_id` and `template_id` arrive as UUIDs."""
    lesson, template = new_id(), new_id()
    response = await api.post(
        f"{BASE}/lesson-plan",
        json={
            "topic": "optics",
            "lesson_id": str(lesson),
            "template_id": str(template),
            "subject_id": str(SUBJECT),
        },
    )

    assert response.status_code == 200, response.text
    args = ai.calls[0][2]
    assert args.lesson_id == lesson and args.template_id == template
    assert args.duration_minutes == 45
    assert UUID(response.json()["id"])


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
async def test_teacher_and_admin_are_allowed(
    api: AsyncClient,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    role: Role,
) -> None:
    """Same rule as the MCP teacher server: teacher or admin."""
    current["actor"] = make_actor(role)

    assert (
        await api.post(f"{BASE}/handout", json=BODIES["/handout"])
    ).status_code == 200


@pytest.mark.parametrize("role", [Role.STUDENT, Role.COUNSELOR])
@pytest.mark.parametrize("path", sorted(BODIES))
async def test_other_roles_are_refused_and_the_model_is_not_called(
    api: AsyncClient,
    ai: RecordingTeacherAi,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    role: Role,
    path: str,
) -> None:
    """403 on every route; nothing reaches the tools (no model spend)."""
    current["actor"] = make_actor(role)

    post = await api.post(BASE + path, json=BODIES[path])
    get = await api.get(f"{BASE}/plan-templates")

    assert post.status_code == 403 and get.status_code == 403
    assert ai.calls == []


async def test_invalid_input_is_a_problem_json(
    api: AsyncClient, ai: RecordingTeacherAi
) -> None:
    """A `TeacherInputError` from the tools is 422 problem+json; a bad body too."""
    ai.fail = TeacherInputError("topic is empty")

    refused = await api.post(f"{BASE}/questions", json=BODIES["/questions"])
    malformed = await api.post(f"{BASE}/questions", json={"count": 5})

    assert refused.status_code == 422
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert malformed.status_code == 422


@pytest.mark.parametrize(
    "path", ["/questions", "/handout", "/work-check", "/lesson-plan"]
)
async def test_generating_routes_require_a_destination_subject(
    api: AsyncClient, ai: RecordingTeacherAi, path: str
) -> None:
    """No `subject_id` -> 422 and no model call: every output must land in a
    notebook."""
    body = {
        k: v for k, v in BODIES[path].items() if k not in ("subject_id", "group_id")
    }

    response = await api.post(BASE + path, json=body)

    assert response.status_code == 422
    assert ai.calls == []


def test_every_method_has_an_http_route_and_an_mcp_tool() -> None:
    """Parity guard: the two surfaces of `TeacherAiTools` cannot drift apart."""
    methods = {
        n
        for n, _ in inspect.getmembers(TeacherAiTools, inspect.isfunction)
        if not n.startswith("_")
    }
    assert methods == set(SURFACES)

    routes = {
        (m, route.path)
        for router in ROUTERS
        for route in router.routes
        for m in getattr(route, "methods", ())
    }
    mcp = server_tools("teacher")
    for method, (verb, path, tool) in SURFACES.items():
        assert (verb, BASE + path) in routes, method
        assert tool in mcp, method


def test_args_dataclasses_are_frozen() -> None:
    """The routes pass immutable args (guards accidental mutation downstream)."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        GenerateQuestionsArgs("t").topic = "x"  # type: ignore[misc]

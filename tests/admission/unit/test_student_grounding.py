"""AI features of admission send the student's own data, and only theirs."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.list_plan import ListPlanService
from app.modules.admission.application.student_context import CAP, student_block
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.ports.consent import AI
from app.modules.admission.ports.student_search import StudentDataHit
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.admission.unit.test_career import CTX, USER, _suggester
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_goal_plan import _suggester as _goal
from tests.admission.unit.test_items_service import OTHER, STUDENT, World
from tests.fakes.admission_student_search import FakeStudentSearch
from tests.fakes.clock import FixedClock


def _hit(title: str, snippet: str, source: str = "item") -> StudentDataHit:
    return StudentDataHit(
        source, str(new_id()), title, snippet, "/x", 1.0  # type: ignore[arg-type]
    )


def _search(word: str = "curious") -> FakeStudentSearch:
    return FakeStudentSearch(
        {
            STUDENT: [_hit("Robotics", f"{word} captain of MINE-ROBOTS club")],
            OTHER: [_hit("Secret", f"{word} THEIR-PRIVATE-DATA")],
        }
    )


def _user(call: dict[str, Any]) -> str:
    return str(call["user"])


async def test_block_caps_and_is_empty_without_hits() -> None:
    s = FakeStudentSearch(
        {STUDENT: [_hit(f"t{n}", "word " * 100, "course") for n in range(40)]}
    )
    lines = await student_block(s, STUDENT, ["word"], ("course",))
    assert lines[0].startswith("Student data (untrusted")
    assert len("\n".join(lines)) <= CAP
    assert await student_block(s, STUDENT, ["nothing"], ()) == []
    assert await student_block(None, STUDENT, ["word"], ()) == []


async def test_goal_plan_prompt_has_own_data_only() -> None:
    reply = {"suggestions": []}
    w = World(reply, reply)
    ctx = await w.ctx()
    svc = _goal(w, {})
    svc._search = _search()
    await svc.suggest(ctx, "en")
    user = _user(w.ai.calls[0])
    assert "MINE-ROBOTS" in user and "THEIR-PRIVATE" not in user
    w2 = World(reply)
    svc2 = _goal(w2, {})
    svc2._search = FakeStudentSearch()
    await svc2.suggest(await w2.ctx(), "en")
    assert "Student data" not in _user(w2.ai.calls[0])


async def test_career_prompt_has_own_data_only() -> None:
    svc, _, ai, _ = _suggester()
    svc._search = FakeStudentSearch(
        {
            USER: [_hit("Robotics", "interests and strengths: MINE-ROBOTS club")],
            OTHER: [_hit("Secret", "interests and strengths: THEIR-PRIVATE-DATA")],
        }
    )
    await svc.professions(CTX, "en")
    user = _user(ai.calls[0])
    assert "MINE-ROBOTS" in user and "THEIR-PRIVATE" not in user
    svc._search = FakeStudentSearch()
    await svc.spike(CTX, "en")
    assert "Student data" not in _user(ai.calls[1])


async def test_essay_prompt_has_own_data_only() -> None:
    reply = {"questions": ["q one"]}
    d = Desk(reply, reply)
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {"prompt_text": "robotics story"})
    d.coach._search = _search("robotics")
    await d.coach.brainstorm(ctx, e.id, "en")
    user = _user(d.w.ai.calls[0])
    assert "MINE-ROBOTS" in user and "THEIR-PRIVATE" not in user
    d.coach._search = FakeStudentSearch()
    await d.coach.brainstorm(ctx, e.id, "en")
    assert "Student data" not in _user(d.w.ai.calls[1])


async def test_list_plan_prompt_has_own_data_only() -> None:
    inst = CatalogInstitution(new_id(), "x", "Uni X", "US", None, "published")

    class Uow:
        catalog = SimpleNamespace(
            institutions=lambda: _aw([inst]), institution=lambda _i: _aw(inst)
        )
        profiles = SimpleNamespace(get=lambda _s: _aw(None))

        async def __aenter__(self) -> "Uow":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class Lists:
        async def view(self, ctx: Any, student_id: UUID) -> list[Any]:
            return []

    class Access:
        async def resolve(self, ctx: Any, student_id: UUID) -> Any:
            return SimpleNamespace(owner=True, permissions=frozenset())

    class Hits:
        async def hit(self, *a: Any, **k: Any) -> None:
            return None

    async def quota(_: UUID) -> int | None:
        return 5

    class Ai2:
        calls: list[dict[str, Any]] = []

        async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
            self.calls.append(kw)
            return {"suggestions": []}, "m"

    ai = Ai2()
    ai.calls = []
    svc = ListPlanService(
        Uow,  # type: ignore[arg-type]
        Access(),  # type: ignore[arg-type]
        Lists(),  # type: ignore[arg-type]
        ai,
        FakeConsents({STUDENT: frozenset({AI})}),
        FixedClock(NOW),
        Hits(),  # type: ignore[arg-type]
        quota,
        BuiltinPrompts(),
        _search("major"),
    )
    ctx = SimpleNamespace(user_id=STUDENT)
    await svc.suggest(ctx, "en")  # type: ignore[arg-type]
    user = _user(ai.calls[0])
    assert "MINE-ROBOTS" in user
    assert "THEIR-PRIVATE" not in user
    svc._search = FakeStudentSearch()
    await svc.suggest(ctx, "en")  # type: ignore[arg-type]
    assert "Student data" not in _user(ai.calls[1])


async def _aw(value: Any) -> Any:
    return value

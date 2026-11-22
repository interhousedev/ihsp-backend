"""Project ideas: brief validation, cleaning, the service and the helper rules."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.project_helpers import ProjectHelperService
from app.modules.admission.application.project_ideas import (
    ProjectIdeaService,
    clean_ideas,
    search_queries,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.project_ideas import (
    HISTORY_KEEP,
    Contacts,
    Helper,
    ProjectRun,
    clean_brief,
    clean_helper_values,
    match_helpers,
)
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.ports.consent import AI
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.admission.unit.test_goal_plan import _Hits
from tests.admission.unit.test_items_service import STUDENT, World
from tests.fakes.clock import FixedClock

import pytest

BRIEF: dict[str, Any] = {
    "likes": "robots and chess",
    "experience": "",
    "hours_per_day": 1.5,
    "teammates": "maybe",
    "teammates_note": "",
    "network": "",
    "budget_min_usd": 0,
    "budget_max_usd": 100,
}
PAGE = "https://example.org/robot-club"


def _idea(title: str, **over: Any) -> dict[str, Any]:
    return {
        "key": title.lower().replace(" ", "-"),
        "title": title,
        "summary": "Build it.",
        "analogs": [
            {"name": "Club", "where": "uzbekistan", "url": PAGE},
            {"name": "Lab", "where": "abroad", "url": "https://made-up.example/x"},
        ],
        "challenges": ["time"],
        "application_effect": "Shows initiative.",
        "first_steps": ["Plan"],
        "help_tags": ["pitching", "nonsense"],
    } | over


def test_brief_is_validated() -> None:
    assert clean_brief(**BRIEF).likes == "robots and chess"
    for bad in (
        {"likes": "  "},
        {"hours_per_day": 20},
        {"teammates": "all"},
        {"budget_min_usd": 500},
    ):
        with pytest.raises(ValidationFailedError):
            clean_brief(**(BRIEF | bad))


def test_clean_ideas_keeps_only_searched_urls_and_known_tags() -> None:
    out = clean_ideas(
        {"projects": [_idea("Robot club"), _idea("robot club"), _idea("Chess app")]},
        {PAGE},
    )
    assert [p.title for p in out] == ["Robot club", "Chess app"]
    assert [a.url for a in out[0].analogs] == [PAGE, None]
    assert out[0].help_tags == ("pitching",)
    with pytest.raises(AiInvalidOutputError):
        clean_ideas({"projects": []}, set())


def test_search_has_an_uzbekistan_query() -> None:
    queries = search_queries(clean_brief(**BRIEF))
    assert len(queries) == 2 and "Uzbekistan" in queries[1]


class _Runs:
    def __init__(self) -> None:
        self.rows: list[ProjectRun] = []

    async def add(self, run: ProjectRun, *, keep: int) -> None:
        self.rows.insert(0, run)
        del self.rows[keep:]

    async def latest(self, student_id: UUID) -> ProjectRun | None:
        return self.rows[0] if self.rows else None

    async def history(self, student_id: UUID, *, limit: int) -> list[ProjectRun]:
        return [r for r in self.rows if r.student_id == student_id][:limit]

    async def get(self, student_id: UUID, run_id: UUID) -> ProjectRun | None:
        return next(
            (r for r in self.rows if r.id == run_id and r.student_id == student_id),
            None,
        )


class _Search:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def search(self, call: Any) -> Any:
        self.calls.append(call.query)
        if self.fail:
            raise RuntimeError("down")
        hit = SimpleNamespace(url=PAGE, title="Robot club", snippet="Kids build")
        return SimpleNamespace(hits=(hit,))


def _service(
    w: World, runs: _Runs, search: _Search, *, consent: bool = True, limit: int = 9
) -> ProjectIdeaService:
    async def quota(_: UUID) -> int | None:
        return limit

    return ProjectIdeaService(
        runs,  # type: ignore[arg-type]
        w.policy,
        w.ai,
        FakeConsents({STUDENT: frozenset({AI} if consent else set())}),
        BuiltinPrompts(),
        FixedClock(NOW),
        _Hits(),  # type: ignore[arg-type]
        quota,
        web_search=search,  # type: ignore[arg-type]
        profile_of=lambda task: None,
    )


async def test_generate_stores_runs_keeps_history_and_survives_search_failure() -> None:
    reply = {"projects": [_idea("Robot club")]}
    w = World(*[reply] * 8)
    runs = _Runs()
    ctx = await w.ctx()
    svc = _service(w, runs, _Search())
    run = await svc.generate(ctx, BRIEF, "en")
    assert run.search_used and run.projects[0].analogs[0].url == PAGE
    for _ in range(HISTORY_KEEP + 1):
        await svc.generate(ctx, BRIEF, "en")
    assert len(runs.rows) == HISTORY_KEEP
    overview = await svc.overview(ctx)
    assert overview.latest is not None and len(overview.history) == HISTORY_KEEP
    quiet = await _service(w, _Runs(), _Search(fail=True)).generate(ctx, BRIEF, "ru")
    assert quiet.search_used is False and quiet.projects


async def test_generate_needs_consent_quota_and_owns_its_runs() -> None:
    w = World({"projects": [_idea("Robot club")]}, {"projects": [_idea("Chess")]})
    ctx = await w.ctx()
    with pytest.raises(ConsentRequiredError):
        await _service(w, _Runs(), _Search(), consent=False).generate(ctx, BRIEF, "en")
    runs = _Runs()
    svc = _service(w, runs, _Search(), limit=1)
    run = await svc.generate(ctx, BRIEF, "en")
    with pytest.raises(RateLimitedError):
        await svc.generate(ctx, BRIEF, "en")
    assert (await svc.get(ctx, run.id)).id == run.id
    with pytest.raises(AdmissionNotFoundError):
        await svc.get(ctx, new_id())


def _helper(name: str, tags: tuple[str, ...], **over: Any) -> Helper:
    return Helper(
        id=new_id(),
        kind=over.pop("kind", "person"),
        name=name,
        description={"en": "x"},
        tags=tags,
        help_types=(),
        expertise_areas=(),
        contacts=Contacts(email="a@b.co"),
        city=None,
        active=over.pop("active", True),
        created_at=NOW,
        updated_at=NOW,
    )


def test_match_prefers_more_shared_tags_and_skips_inactive() -> None:
    one = _helper("B", ("pitching",))
    two = _helper("A", ("pitching", "fundraising"))
    off = _helper("C", ("pitching",), active=False)
    other = _helper("D", ("website_tech",))
    got = match_helpers([one, two, off, other], ["pitching", "fundraising"])
    assert [h.name for h in got] == ["A", "B"]


def test_helper_values_need_a_contact_a_tag_and_valid_kind() -> None:
    values = {
        "kind": "person",
        "name": "Ann",
        "description": {"en": "Mentor"},
        "tags": ["pitching"],
        "help_types": ["mentoring"],
        "expertise_areas": ["design"],
        "contacts": {
            "email": "a@b.co",
            "phone": None,
            "telegram": None,
            "website": None,
        },
        "city": None,
        "active": True,
    }
    assert clean_helper_values(values)["contacts"].email == "a@b.co"
    for bad in (
        {"kind": "robot"},
        {"tags": []},
        {"contacts": {"email": None, "phone": None, "telegram": None, "website": None}},
        {"description": {}},
    ):
        with pytest.raises(ValidationFailedError):
            clean_helper_values(values | bad)


class _Helpers:
    def __init__(self) -> None:
        self.rows: dict[UUID, Helper] = {}

    async def list(self, *, active_only: bool) -> list[Helper]:
        return [h for h in self.rows.values() if h.active or not active_only]

    async def get(self, helper_id: UUID) -> Helper | None:
        return self.rows.get(helper_id)

    async def save(self, helper: Helper) -> Helper:
        self.rows[helper.id] = helper
        return helper

    async def delete(self, helper_id: UUID) -> bool:
        return self.rows.pop(helper_id, None) is not None


class _AuditUow:
    def __init__(self, log: list[str]) -> None:
        self.access = SimpleNamespace(audit=lambda e: log.append(e.action))
        self._log = log

    async def __aenter__(self) -> "_AuditUow":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


async def test_staff_crud_is_gated_and_audited() -> None:
    log: list[str] = []
    ctx = SimpleNamespace(user_id=new_id())
    repo = _Helpers()

    def service(curator: bool) -> ProjectHelperService:
        return ProjectHelperService(
            repo,  # type: ignore[arg-type]
            lambda: _AuditUow(log),  # type: ignore[arg-type, return-value]
            lambda _c: curator,
            FixedClock(NOW),
        )

    values = {
        "kind": "organization",
        "name": "Lab",
        "description": {"en": "Space"},
        "tags": ["product_dev"],
        "help_types": ["equipment_space"],
        "expertise_areas": [],
        "contacts": {
            "email": None,
            "phone": None,
            "telegram": None,
            "website": "https://lab.example",
        },
        "city": "Tashkent",
        "active": False,
    }
    with pytest.raises(AdmissionForbiddenError):
        await service(False).create(ctx, values)  # type: ignore[arg-type]
    svc = service(True)
    made = await svc.create(ctx, values)  # type: ignore[arg-type]
    assert made.created_by == ctx.user_id
    assert await svc.for_tags(["product_dev"]) == []
    assert len(await svc.list_all(ctx)) == 1  # type: ignore[arg-type]
    active = values | {"active": True}
    saved = await svc.update(ctx, made.id, active)  # type: ignore[arg-type]
    assert [h.id for h in await svc.for_tags(["product_dev"])] == [saved.id]
    await svc.delete(ctx, made.id)  # type: ignore[arg-type]
    with pytest.raises(AdmissionNotFoundError):
        await svc.delete(ctx, made.id)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailedError):
        await svc.for_tags(["bogus"])
    assert log == [
        "project_helper.created",
        "project_helper.edited",
        "project_helper.deleted",
    ]

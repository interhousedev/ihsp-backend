"""Career exploration: cleaning of AI drafts, fake documents, consent and quota."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.career_suggest import (
    CareerSuggester,
    clean_fit,
    clean_professions,
    clean_spike,
)
from app.modules.admission.domain.career import (
    PROFESSIONS_MAX,
    CareerMajor,
    CareerPlan,
    CareerQuestion,
    Profession,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
)
from app.modules.admission.domain.professions import Ikigai, ProfessionPlan
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import career as prompt
from app.modules.admission.ports.consent import AI
from app.modules.ai.infrastructure.fake_career import build_career_document
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeConsents

import jsonschema  # type: ignore[import-untyped]
import pytest

USER = new_id()
ITEM = new_id()
QUESTION = CareerQuestion(
    new_id(), "interests", {"uz": "S", "ru": "В", "en": "What do you enjoy?"}
)
MAJORS = [
    CareerMajor(
        new_id(), "computer_science", "stem", {"uz": "a", "ru": "b", "en": "CS"}
    ),
    CareerMajor(new_id(), "biology", "stem", {"uz": "a", "ru": "b", "en": "Bio"}),
]


def test_clean_professions_dedupes_strips_and_caps() -> None:
    raw = [{"title": "  Pilot ", "reason": "r"}, {"title": "pilot"}]
    raw += [{"title": f"Job {i}", "reason": "x"} for i in range(20)]
    out = clean_professions({"professions": raw})
    assert out[0] == Profession("Pilot", "r")
    assert len(out) == PROFESSIONS_MAX


def test_clean_fit_keeps_known_codes_clamped_best_first() -> None:
    data = {
        "fit": [
            {"code": "biology", "score": 40, "reason": "ok"},
            {"code": "astrology", "score": 99, "reason": "x"},
            {"code": "COMPUTER_SCIENCE", "score": 140, "reason": "great"},
            {"code": "biology", "score": 10, "reason": "dup"},
        ]
    }
    out = clean_fit(data, {"biology", "computer_science"})
    assert [(f.code, f.score) for f in out] == [
        ("computer_science", 100),
        ("biology", 40),
    ]


def test_clean_spike_drops_foreign_evidence() -> None:
    foreign = str(new_id())
    data = {
        "title": "Maker",
        "summary": "Builds",
        "evidence": [
            {"item_id": str(ITEM), "note": "n"},
            {"item_id": foreign, "note": "x"},
            {"item_id": str(ITEM), "note": "dup"},
        ],
        "gaps": ["a", "a", ""],
    }
    spike = clean_spike(data, {str(ITEM)})
    assert [e.item_id for e in spike.evidence] == [ITEM]
    assert spike.gaps == ("a",)
    assert spike.confirmed_at is None


@pytest.mark.parametrize(
    ("name", "schema"),
    [
        (prompt.PROFESSIONS_SCHEMA_NAME, prompt.PROFESSIONS_SCHEMA),
        (prompt.MAJORS_SCHEMA_NAME, prompt.MAJORS_SCHEMA),
        (prompt.SPIKE_SCHEMA_NAME, prompt.SPIKE_SCHEMA),
    ],
)
def test_fake_documents_are_schema_valid(name: str, schema: dict[str, Any]) -> None:
    user = f"[major] biology: Bio\n[item:{ITEM}] {{}}"
    doc = build_career_document(name, [{"role": "user", "content": user}])
    assert doc is not None
    jsonschema.validate(doc, schema)


def test_fake_documents_point_at_real_rows() -> None:
    user = f"[major] biology: Bio\n[item:{ITEM}] {{}}"
    msgs = [{"role": "user", "content": user}]
    fit = clean_fit(build_career_document("career_majors", msgs) or {}, {"biology"})
    assert [f.code for f in fit] == ["biology"]
    spike = clean_spike(build_career_document("career_spike", msgs) or {}, {str(ITEM)})
    assert [e.item_id for e in spike.evidence] == [ITEM]


# --- the suggester --------------------------------------------------------


class Career:
    def __init__(self) -> None:
        self.saved: list[CareerPlan] = []

    async def plan(self, student_id: UUID) -> CareerPlan | None:
        return self.saved[-1] if self.saved else None

    async def questions(self, *, active_only: bool) -> list[CareerQuestion]:
        return [QUESTION]

    async def majors(self, *, active_only: bool) -> list[CareerMajor]:
        return MAJORS

    async def save_plan(self, plan: CareerPlan) -> CareerPlan:
        self.saved.append(plan)
        return plan


class Items:
    async def list_for(self, student_id: UUID) -> list[Any]:
        return []

    async def metrics_for(self, ids: list[UUID]) -> dict[UUID, Any]:
        return {}


class Plans:
    async def get(self, student_id: UUID) -> ProfessionPlan:
        return ProfessionPlan(student_id, ikigai=Ikigai(love=("chess",)))


class Uow:
    def __init__(self, career: Career) -> None:
        self.career, self.items = career, Items()
        self.profession_plans = Plans()

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class Access:
    def __init__(self, owner: bool = True) -> None:
        self.owner = owner

    async def resolve(self, ctx: Any, student_id: UUID) -> Any:
        return SimpleNamespace(owner=self.owner)


class Ai:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kw)
        msgs = [{"role": "user", "content": kw["user"]}]
        return build_career_document(kw["schema_name"], msgs) or {}, "fake"


class Limiter:
    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.hits.append((key, limit))


def _suggester(
    grants: frozenset[str] = frozenset({AI}), owner: bool = True
) -> tuple[Any, ...]:
    career, ai, limiter = Career(), Ai(), Limiter()

    async def weekly(user_id: UUID) -> int | None:
        return 10

    svc = CareerSuggester(
        lambda: Uow(career),  # type: ignore[arg-type, return-value]
        Access(owner),  # type: ignore[arg-type]
        ai,
        FakeConsents({USER: grants}),
        limiter,  # type: ignore[arg-type]
        weekly,
        BuiltinPrompts(),
    )
    return svc, career, ai, limiter


CTX: Any = SimpleNamespace(user_id=USER)


async def test_suggestions_in_fake_mode_store_drafts() -> None:
    svc, career, ai, limiter = _suggester()
    plan = await svc.professions(CTX, "en")
    assert [p.title for p in plan.professions][:1] == ["Software engineer"]
    plan = await svc.majors_fit(CTX, "en")
    assert [f.code for f in plan.fit] == ["computer_science", "biology"]
    plan = await svc.spike(CTX, "en")
    assert plan.spike is not None and plan.spike.confirmed_at is None
    assert [c["task"] for c in ai.calls] == [
        AiTask.ADMIT_CAREER_PROFESSIONS,
        AiTask.ADMIT_CAREER_MAJORS,
        AiTask.ADMIT_CAREER_SPIKE,
    ]
    assert limiter.hits == [(f"admission:career:{USER}", 10)] * 3
    assert "<student_text>" in ai.calls[0]["user"]
    assert "[ikigai:love] chess" in ai.calls[0]["user"]


async def test_shortlisted_professions_survive_new_suggestions() -> None:
    svc, career, _, _ = _suggester()
    career.saved.append(
        CareerPlan(USER, professions=[Profession("Pilot", "r", shortlisted=True)])
    )
    plan = await svc.professions(CTX, "en")
    assert plan.professions[0] == Profession("Pilot", "r", shortlisted=True)
    assert len(plan.professions) == 4


async def test_suggestions_need_ai_consent_and_ownership() -> None:
    svc, career, ai, limiter = _suggester(frozenset())
    with pytest.raises(ConsentRequiredError):
        await svc.professions(CTX, "en")
    svc2, *_ = _suggester(owner=False)
    with pytest.raises(AdmissionForbiddenError):
        await svc2.spike(CTX, "en")
    assert ai.calls == [] and limiter.hits == [] and career.saved == []

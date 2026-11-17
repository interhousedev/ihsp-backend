"""Per-university advice: fake AI, cache, invalidation, consent and quota."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.uni_advice import UniAdviceService
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.uni_chat import CachedWeb
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import uni_advice as prompt
from app.modules.admission.ports.consent import AI
from app.modules.ai.infrastructure.fake_uni_advice import build_uni_advice_document
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents, FakeStore, FakeUow
from tests.fakes.clock import FixedClock

import jsonschema  # type: ignore[import-untyped]
import pytest

USER = new_id()
CTX: Any = SimpleNamespace(
    user_id=USER,
    actor=SimpleNamespace(user_id=USER),
    admission=SimpleNamespace(is_applicant=True),
)


class Repo:
    def __init__(self) -> None:
        self.cache: dict[tuple[str, str], CachedWeb] = {}

    async def cached(self, kind: str, key: str) -> CachedWeb | None:
        return self.cache.get((kind, key))

    async def store(
        self, kind: str, key: str, payload: dict[str, Any], now: dt.datetime
    ) -> None:
        self.cache[(kind, key)] = CachedWeb(payload, now)


class Data:
    def __init__(self) -> None:
        self.items_: list[dict[str, Any]] = [{"title": "Robotics club"}]
        self.prof: dict[str, Any] = {"grade": 11}

    async def profile(self, student_id: UUID) -> dict[str, Any]:
        return self.prof

    async def test_scores(self, student_id: UUID) -> list[dict[str, Any]]:
        return []

    async def items(self, student_id: UUID) -> list[dict[str, Any]]:
        return self.items_


class Ai:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kw)
        msgs = [{"role": "user", "content": kw["user"]}]
        doc = build_uni_advice_document(kw["schema_name"], msgs)
        assert doc is not None
        return doc, "fake"


class Limiter:
    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.hits.append((key, limit))


class Access:
    def __init__(self, owner: bool = True) -> None:
        self.owner = owner

    async def resolve(self, ctx: Any, student_id: UUID) -> Any:
        return SimpleNamespace(owner=self.owner)


def build(grants: frozenset[str] = frozenset({AI}), owner: bool = True) -> Any:
    store = FakeStore()
    inst = CatalogInstitution(new_id(), "u", "Uni", "US", None, "published")
    store.institutions[inst.id] = inst
    repo, data, ai, limiter, clock = (
        Repo(),
        Data(),
        Ai(),
        Limiter(),
        FixedClock(NOW),
    )

    async def weekly(user_id: UUID) -> int | None:
        return 7

    svc = UniAdviceService(
        lambda: FakeUow(store),  # type: ignore[arg-type,return-value]
        Access(owner),  # type: ignore[arg-type]
        FakeConsents({USER: grants}),
        repo,
        data,
        ai,
        limiter,  # type: ignore[arg-type]
        weekly,
        BuiltinPrompts(),
        clock,
    )
    return svc, repo, data, ai, limiter, clock, inst.id


def test_fake_document_matches_the_strict_schema() -> None:
    doc = build_uni_advice_document(
        prompt.SCHEMA_NAME, [{"content": "University: MIT (Cambridge, US)"}]
    )
    assert doc is not None and "MIT" in doc["questions"][0]
    jsonschema.validate(doc, prompt.SCHEMA)
    assert prompt.SCHEMA_NAME == "uni_advice"


async def test_advice_is_generated_cached_and_counted() -> None:
    svc, _, _, ai, limiter, _, inst = build()
    first = await svc.advice(CTX, inst, "en")
    assert first.questions and first.academic and first.activities
    again = await svc.advice(CTX, inst, "en")
    assert again == first and len(ai.calls) == 1
    assert ai.calls[0]["task"] == AiTask.ADMIT_UNI_ADVICE
    assert limiter.hits == [(f"admission:uni_advice:{USER}", 7)]


async def test_changed_items_invalidate_the_cache() -> None:
    svc, _, data, ai, _, _, inst = build()
    await svc.advice(CTX, inst, "en")
    data.items_ = [{"title": "Debate"}]
    await svc.advice(CTX, inst, "en")
    assert len(ai.calls) == 2


async def test_changed_profile_invalidates_the_cache() -> None:
    svc, _, data, ai, _, _, inst = build()
    await svc.advice(CTX, inst, "en")
    data.prof = {"grade": 12}
    await svc.advice(CTX, inst, "en")
    assert len(ai.calls) == 2


async def test_cache_expires_after_14_days() -> None:
    svc, _, _, ai, _, clock, inst = build()
    await svc.advice(CTX, inst, "en")
    clock.advance(days=13)
    await svc.advice(CTX, inst, "en")
    assert len(ai.calls) == 1
    clock.advance(days=2)
    await svc.advice(CTX, inst, "en")
    assert len(ai.calls) == 2


async def test_without_consent_only_static_questions() -> None:
    svc, repo, _, ai, limiter, _, inst = build(grants=frozenset())
    out = await svc.advice(CTX, inst, "ru")
    assert out.questions and out.academic == [] and out.activities == []
    assert ai.calls == [] and limiter.hits == [] and repo.cache == {}


async def test_only_the_owning_applicant() -> None:
    svc, _, _, _, _, _, inst = build(owner=False)
    with pytest.raises(AdmissionForbiddenError):
        await svc.advice(CTX, inst, "en")

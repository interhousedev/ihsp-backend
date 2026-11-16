"""Profile, words and alignment services."""

from typing import Any

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.profile import ProfileService
from app.modules.admission.application.profile_alignment import AlignmentService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.words import WordsService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
    InvalidAnswerError,
    QuotaExceededError,
    WordsNotSetError,
)
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeAi,
    FakeConsents,
    FakeMembership,
    FakeStore,
    student_ref,
)
from tests.admission.unit.test_items_service import ItemsData, ItemsUow
from tests.fakes.clock import FixedClock

import pytest

STUDENT = new_id()
OTHER = new_id()


def _weekly(value: int) -> Any:
    async def read(user_id: Any) -> int | None:
        return value

    return read


class Kit:
    """Services over one store."""

    def __init__(self, reply: dict[str, Any] | None = None, limit: int = 5) -> None:
        """Wire everything."""
        self.store = FakeStore()
        self.ai = FakeAi(reply or {})
        membership = FakeMembership(
            [student_ref(STUDENT, new_id()), student_ref(OTHER, new_id())]
        )
        clock = FixedClock(NOW)
        consents = FakeConsents({STUDENT: frozenset({"admission_ai"})})
        self.items = ItemsData()
        uow = lambda: ItemsUow(self.store, self.items)  # noqa: E731
        access = AccessPolicy(uow, membership, consents, clock, {10, 11})
        runtime = RuntimeSettingsService(uow, ttl=0)
        self.profile = ProfileService(uow, access, runtime, clock)
        self.words = WordsService(
            uow, access, self.ai, consents, clock, BuiltinPrompts()
        )
        self.align = AlignmentService(
            uow, access, self.ai, consents, clock, _weekly(limit), BuiltinPrompts()
        )
        self.resolver = ResolveAdmissionActor(uow, membership, clock, {10, 11})

    async def ctx(self, user: Any = STUDENT) -> AdmissionContext:
        """Return the context of a student."""
        return await self.resolver.execute(Actor(user, frozenset({Role.STUDENT})))


async def test_profile_validation_resume_and_lock() -> None:
    k = Kit()
    ctx = await k.ctx()
    first = await k.profile.get(ctx, STUDENT)
    assert first.next_question == "q01" and not first.setup_completed
    with pytest.raises(InvalidAnswerError):
        await k.profile.save(ctx, {"q06": "maybe"}, None)
    with pytest.raises(CharLimitError):
        await k.profile.save(ctx, {"q20": "x" * 201}, None)
    view = await k.profile.save(ctx, {"q01": "Ali", "q06": "yes"}, None)
    assert view.answers == {"q01": "Ali", "q06": "yes"}
    assert view.next_question == "q02"
    with pytest.raises(AdmissionConflictError):
        await k.profile.save(ctx, {"q01": "Bob"}, None)
    again = await k.profile.save(ctx, {"q01": "Bob"}, view.lock_version)
    assert again.lock_version == view.lock_version + 1


async def test_hidden_question_and_stranger() -> None:
    k = Kit()
    ctx = await k.ctx()
    with pytest.raises(AdmissionNotFoundError):
        await k.profile.save(ctx, {"q38": True}, None)  # alumni only
    other = await k.ctx(OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await k.profile.get(other, STUDENT)


async def test_words_version_source_and_history() -> None:
    k = Kit(
        {
            "candidates": [
                {"word": "Curious", "reason": "**r**", "evidence_refs": ["answer:q20"]},
                {"word": "curious", "reason": "dup", "evidence_refs": []},
                {"word": "Kind", "reason": "r", "evidence_refs": ["answer:zzz"]},
            ]
        }
    )
    ctx = await k.ctx()
    await k.profile.save(ctx, {"q20": "I love asking why"}, None)
    state = await k.words.suggest(ctx)
    assert [c["word"] for c in state.candidates] == ["Curious", "Kind"]
    assert state.candidates[0]["evidence_refs"] == ["q20"]
    assert state.candidates[0]["reason"] == "r"
    assert state.candidates[1]["evidence_refs"] == []
    with pytest.raises(InvalidAnswerError):
        await k.words.set(ctx, ["a", "A", "b"], state.lock_version)
    with pytest.raises(AdmissionConflictError):
        await k.words.set(ctx, ["a", "b", "c"], 99)
    done = await k.words.set(ctx, ["Curious", "Kind", "Bold"], state.lock_version)
    assert (done.version, done.source) == (1, "mixed")
    assert len(k.store.words_history) == 1


async def test_suggest_needs_consent() -> None:
    k = Kit()
    ctx = await k.ctx(OTHER)
    with pytest.raises(ConsentRequiredError):
        await k.words.suggest(ctx)


def _map(refs: list[dict[str, Any]], safe: bool = False) -> dict[str, Any]:
    return {
        "safeguarding_concern": safe,
        "words": [{"word": "Curious", "carriers": refs}],
        "orphans": [{"ref_kind": "answer", "ref_id": "q21"}],
        "gaps": [
            {"word": "Curious", "advice": "**add**"},
            {"word": "X", "advice": "n"},
        ],
    }


async def _ready(k: Kit) -> AdmissionContext:
    ctx = await k.ctx()
    await k.profile.save(ctx, {"q20": "why", "q21": "teamwork"}, None)
    await k.words.set(ctx, ["Curious", "Kind", "Bold"], 0)
    return ctx


async def _lock(k: Kit, ctx: AdmissionContext) -> int:
    return (await k.profile.get(ctx, STUDENT)).lock_version


async def test_alignment_requires_words() -> None:
    k = Kit()
    with pytest.raises(WordsNotSetError):
        await k.align.run(await k.ctx())


async def test_alignment_cache_validation_and_stale() -> None:
    carriers = [
        {"ref_kind": "answer", "ref_id": "q20", "strength": "strong"},
        {"ref_kind": "answer", "ref_id": "nope", "strength": "strong"},
    ]
    k = Kit(_map(carriers))
    ctx = await _ready(k)
    first = await k.align.run(ctx)
    assert (await k.align.run(ctx)).review == first.review
    assert k.ai.calls == 1
    p = first.review.payload
    assert [c["ref_id"] for c in p["words"][0]["carriers"]] == ["q20"]
    assert [w["word"] for w in p["words"]] == ["Curious", "Kind", "Bold"]
    assert first.review.grades["Curious"] == "strong"
    assert first.review.overall == "D"
    assert p["orphans"] == [{"ref_kind": "answer", "ref_id": "q21"}]
    assert p["gaps"] == [{"word": "Curious", "advice": "add"}]
    latest = await k.align.latest(ctx, STUDENT)
    assert latest is not None and not latest.stale
    await k.profile.save(ctx, {"q21": "changed"}, await _lock(k, ctx))
    latest = await k.align.latest(ctx, STUDENT)
    assert latest is not None and latest.stale


async def test_alignment_safeguarding_has_no_grade() -> None:
    k = Kit(_map([], safe=True))
    ctx = await _ready(k)
    r = (await k.align.run(ctx)).review
    assert r.safety_flag == "safeguarding"
    assert r.overall is None and r.grades == {}
    assert r.payload == {"message_key": "admission-safeguarding-support"}


async def test_alignment_quota() -> None:
    k = Kit(_map([]), limit=1)
    ctx = await _ready(k)
    await k.align.run(ctx)
    await k.profile.save(ctx, {"q21": "changed"}, await _lock(k, ctx))
    with pytest.raises(QuotaExceededError):
        await k.align.run(ctx)

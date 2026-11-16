"""Essays: autosave lock, interval snapshots, restore, sharing scope, AI gate."""

from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.admission.application.essays import (
    EssayCoach,
    EssayService,
    UowEssayReader,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
)
from app.modules.admission.domain.essays import (
    SNAPSHOT_INTERVAL,
    Essay,
    EssayIdea,
    EssayVersion,
)
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import essays as prompts
from app.modules.admission.ports.consent import AI, STAFF_VIEW
from app.shared.actor import Actor, Role
from app.shared.base_error import RateLimitedError
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.admission.unit.test_access_policy import STAFF, _assign
from tests.admission.unit.test_items_service import (
    OTHER,
    STUDENT,
    ItemsUow,
    World,
)
from tests.fakes.clock import FixedClock

import pytest


class MemEssays:
    """An EssayRepository over dicts, with the SQL compare-and-set semantics."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Essay] = {}
        self.vers: dict[UUID, dict[int, EssayVersion]] = {}
        self.idea_rows: dict[UUID, EssayIdea] = {}

    async def list_for(self, student_id: UUID) -> list[Essay]:
        return [e for e in self.rows.values() if e.student_id == student_id]

    async def get(self, essay_id: UUID) -> Essay | None:
        return self.rows.get(essay_id)

    async def add(self, essay: Essay) -> Essay:
        self.rows[essay.id] = essay
        return essay

    async def update(self, essay: Essay) -> Essay:
        row = self.rows.get(essay.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != essay.lock_version:
            raise AdmissionConflictError()
        stored = replace(essay, lock_version=essay.lock_version + 1)
        self.rows[essay.id] = stored
        return stored

    async def delete(self, essay_id: UUID) -> None:
        self.rows.pop(essay_id, None)
        self.vers.pop(essay_id, None)

    async def versions(self, essay_id: UUID) -> list[EssayVersion]:
        found = self.vers.get(essay_id, {})
        return [found[k] for k in sorted(found, reverse=True)]

    async def version(self, essay_id: UUID, version: int) -> EssayVersion | None:
        return self.vers.get(essay_id, {}).get(version)

    async def add_version(self, version: EssayVersion) -> EssayVersion:
        self.vers.setdefault(version.essay_id, {})[version.version] = version
        return version

    async def set_shared(
        self, essay_id: UUID, version: int, shared: bool
    ) -> EssayVersion | None:
        found = self.vers.get(essay_id, {}).get(version)
        if found is None:
            return None
        out = replace(found, shared=shared)
        self.vers[essay_id][version] = out
        return out

    async def ideas_for(self, student_id: UUID) -> list[EssayIdea]:
        return [i for i in self.idea_rows.values() if i.student_id == student_id]

    async def get_idea(self, idea_id: UUID) -> EssayIdea | None:
        return self.idea_rows.get(idea_id)

    async def add_idea(self, idea: EssayIdea) -> EssayIdea:
        self.idea_rows[idea.id] = idea
        return idea

    async def update_idea(self, idea: EssayIdea) -> EssayIdea:
        if self.idea_rows[idea.id].lock_version != idea.lock_version:
            raise AdmissionConflictError()
        stored = replace(idea, lock_version=idea.lock_version + 1)
        self.idea_rows[idea.id] = stored
        return stored

    async def delete_idea(self, idea_id: UUID) -> None:
        self.idea_rows.pop(idea_id, None)


class _Hits:
    def __init__(self) -> None:
        self.count = 0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.count += 1
        if self.count > limit:
            raise RateLimitedError(params={"retry_after": 1})
        return self.count


class Desk:
    def __init__(self, *replies: dict[str, Any], consent: bool = True) -> None:
        self.w = World(*replies)
        self.repo = MemEssays()
        self.clock = FixedClock(NOW)
        self.consents = FakeConsents(
            {STUDENT: frozenset({STAFF_VIEW, AI} if consent else {STAFF_VIEW})}
        )

        def uow() -> Any:
            u = ItemsUow(self.w.store, self.w.data)
            u.essays = self.repo  # type: ignore[attr-defined]
            return u

        async def quota(_: UUID) -> int | None:
            return 2

        self.svc = EssayService(uow, self.w.policy, self.clock)
        self.coach = EssayCoach(
            uow,
            self.w.policy,
            self.w.ai,
            self.consents,
            self.clock,
            _Hits(),  # type: ignore[arg-type]
            quota,
            BuiltinPrompts(),
        )
        self.reader = UowEssayReader(uow)

    async def staff(self, scope: str, ref: UUID | None) -> Any:
        self.w.store.assignments[STAFF] = (_assign("counselor_full", scope, ref),)
        return await self.w.resolver.execute(Actor(STAFF, frozenset({Role.COUNSELOR})))


async def test_autosave_conflict_on_stale_lock() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {"title": "Why me", "word_limit": 650})
    saved = await d.svc.save(ctx, e.id, 0, {"body": "one two three"})
    assert saved.lock_version == 1 and saved.word_count == 3
    with pytest.raises(AdmissionConflictError):
        await d.svc.save(ctx, e.id, 0, {"body": "stale tab"})
    assert (await d.svc.get(ctx, e.id)).body == "one two three"


async def test_patch_null_clears_word_limit_and_omitted_keeps_it() -> None:
    from app.interfaces.http.v1.admission.routes_essays import EssayPatchIn

    d = Desk()
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {"title": "Why me", "word_limit": 650})
    keep = EssayPatchIn.model_validate({"lock_version": 0, "title": "New"})
    changes = keep.model_dump(exclude_unset=True, exclude={"lock_version"})
    saved = await d.svc.save(ctx, e.id, 0, changes)
    assert saved.word_limit == 650
    clear = EssayPatchIn.model_validate({"lock_version": 1, "word_limit": None})
    changes = clear.model_dump(exclude_unset=True, exclude={"lock_version"})
    saved = await d.svc.save(ctx, e.id, 1, changes)
    assert saved.word_limit is None


async def test_supplemental_needs_shortlist_entry_and_word_limit_bounds() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    with pytest.raises(CharLimitError):
        await d.svc.create(ctx, {"kind": "supplemental"})
    with pytest.raises(CharLimitError):
        await d.svc.create(ctx, {"word_limit": 0})


async def test_interval_snapshot_explicit_version_and_restore() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {})
    e = await d.svc.save(ctx, e.id, e.lock_version, {"body": "first draft"})
    assert [v.source for v in await d.svc.versions(ctx, e.id)] == ["interval"]
    e = await d.svc.save(ctx, e.id, e.lock_version, {"body": "first draft more"})
    assert len(await d.svc.versions(ctx, e.id)) == 1  # inside the interval
    d.clock.advance(seconds=SNAPSHOT_INTERVAL.total_seconds() + 1)
    e = await d.svc.save(ctx, e.id, e.lock_version, {"body": "second draft"})
    assert e.current_version == 2
    e = await d.svc.save(ctx, e.id, e.lock_version, {"body": "unsaved words"})
    restored = await d.svc.restore(ctx, e.id, 1, e.lock_version)
    assert restored.body == "first draft"
    vs = await d.svc.versions(ctx, e.id)
    assert [v.source for v in vs][:2] == ["restore", "explicit"]
    assert vs[1].body == "unsaved words"
    named = await d.svc.snapshot(ctx, e.id, restored.lock_version, "  Final  ")
    assert named.name == "Final" and named.source == "explicit"
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.versions(await d.w.ctx(OTHER), e.id)


async def test_staff_see_only_shared_versions_in_scope() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {"notes": "private notes"})
    e = await d.svc.save(ctx, e.id, e.lock_version, {"body": "draft one"})
    await d.svc.snapshot(ctx, e.id, e.lock_version)
    staff = await d.staff("all", None)
    assert await d.svc.list_shared(staff, STUDENT) == []
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.shared_view(staff, e.id)
    await d.svc.share(ctx, e.id, 1, True)
    view = await d.svc.shared_view(staff, e.id)
    assert [v.version for v in view.versions] == [1]
    assert view.essay.body == "" and view.essay.notes == ""
    [only] = await d.svc.list_shared(staff, STUDENT)
    assert only.versions[0].body == "draft one"
    outside = await d.staff("student", OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.shared_view(outside, e.id)
    [text] = await d.reader.latest_for(STUDENT, shared_only=True)
    assert text.body == "draft one"
    await d.svc.share(ctx, e.id, 1, False)
    assert await d.reader.latest_for(STUDENT, shared_only=True) == []


async def test_coach_needs_consent_and_quota_and_cleans_output() -> None:
    reply = {"questions": ["**When** did you change?", "", "What did you build?"]}
    d = Desk(reply, reply)
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {"prompt_text": "Tell us about you"})
    questions = await d.coach.brainstorm(ctx, e.id, "en")
    assert questions and all(q.strip() for q in questions)
    assert d.w.ai.calls[0]["task"].value == "admit_essay_coach"
    with pytest.raises(CharLimitError):
        await d.coach.feedback(ctx, e.id, "en")  # empty draft
    await d.coach.brainstorm(ctx, e.id, "en")
    with pytest.raises(RateLimitedError):
        await d.coach.brainstorm(ctx, e.id, "en")
    d.consents.grants[OTHER] = frozenset({AI})
    with pytest.raises(AdmissionNotFoundError):
        await d.coach.brainstorm(await d.w.ctx(OTHER), e.id, "en")


@pytest.mark.parametrize("granted", [None, frozenset({STAFF_VIEW})])
async def test_coach_refuses_without_ai_consent(
    granted: frozenset[str] | None,
) -> None:
    d = Desk()
    ctx = await d.w.ctx()
    e = await d.svc.create(ctx, {})
    if granted is None:
        d.consents.grants.pop(STUDENT)
    else:
        d.consents.grants[STUDENT] = granted
    for call in (d.coach.brainstorm, d.coach.outline, d.coach.feedback):
        with pytest.raises(ConsentRequiredError):
            await call(ctx, e.id, "en")
    assert d.w.ai.calls == []


def test_strict_schemas_cover_every_helper() -> None:
    assert set(prompts.PROMPTS) == set(prompts.SCHEMAS)
    for _, schema in prompts.SCHEMAS.values():
        assert schema["additionalProperties"] is False

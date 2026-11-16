"""Full application review: fan-out, lead merge, degradation, consent and access."""

import dataclasses
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.app_review import AppReviewService
from app.modules.admission.domain.access import Resolution
from app.modules.admission.domain.app_review import AppReview
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import app_review as prompt
from app.modules.admission.ports.app_review import ReviewInputs
from app.modules.admission.ports.consent import AI
from app.modules.ai.infrastructure.fake_schema import document_for
from app.shared.ai_tasks import AiTask
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest

STUDENT = new_id()
COUNSELOR = new_id()
LEAD = AiTask.ADMIT_APP_REVIEW_LEAD


class Repo:
    def __init__(self) -> None:
        self.rows: dict[UUID, AppReview] = {}
        self.snapshots: list[tuple[str, int]] = []

    async def add(self, review: AppReview) -> AppReview:
        mine = [
            r.version for r in self.rows.values() if r.student_id == review.student_id
        ]
        stored = dataclasses.replace(review, version=max(mine, default=0) + 1)
        self.rows[stored.id] = stored
        return stored

    async def get(self, review_id: UUID) -> AppReview | None:
        return self.rows.get(review_id)

    async def list_for(self, student_id: UUID, *, limit: int = 20) -> list[AppReview]:
        rows = [r for r in self.rows.values() if r.student_id == student_id]
        return sorted(rows, key=lambda r: -r.version)[:limit]

    async def save(self, review: AppReview) -> None:
        self.rows[review.id] = review
        self.snapshots.append((review.status, len(review.sections)))


class Inputs:
    def __init__(self, data: ReviewInputs) -> None:
        self.data = data

    async def load(self, student_id: UUID) -> ReviewInputs:
        return self.data


class Access:
    def __init__(self, res: Resolution) -> None:
        self.res = res

    async def resolve(self, ctx: Any, student_id: UUID) -> Resolution:
        return self.res

    async def require(
        self, ctx: Any, student_id: UUID, *_: Any, **__: Any
    ) -> Resolution:
        if not self.res.in_scope:
            raise AdmissionNotFoundError()
        return self.res


class Ai:
    def __init__(self, fail: set[AiTask] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[AiTask, str]] = []

    async def json(
        self, *, task: AiTask, user: str, schema: dict[str, Any], **_: Any
    ) -> tuple[dict[str, Any], str]:
        self.calls.append((task, user))
        if task in self.fail:
            raise RuntimeError("provider down")
        doc = document_for(schema)
        if task is LEAD:
            doc["headline"] = "Strong <b>spike</b>"
            doc["next_actions"] = [
                {"title": "Later", "why": "w", "section": "essays", "priority": 3},
                {"title": "Now", "why": "w", "section": "profile", "priority": 1},
            ]
        else:
            doc["score"] = 6
            doc["findings"] = [
                {"kind": "strength", "text": "Good", "evidence": ["item:1", "bogus"]}
            ]
        return doc, "m-lead" if task is LEAD else "m-section"


class Limiter:
    def __init__(self, allow: int = 99) -> None:
        self.allow = allow
        self.hits = 0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.hits += 1
        if self.hits > min(limit, self.allow):
            raise RateLimitedError()


FULL = ReviewInputs(
    words=("curious", "builder", "kind"),
    profile=[("answer:q1", "I like robots")],
    items=[("item:1", "Robotics club lead")],
    essays=[("essay:1", "My essay")],
    courses=[("course:1", "Physics A")],
    universities=[("entry:1", "MIT, reach")],
    readiness=[("document:1", "Transcript: ready")],
    staff_visible=True,
)
OWNER = Resolution(permissions=frozenset(), in_scope=True, owner=True)


def _svc(
    *,
    ai: Ai | None = None,
    consent: bool = True,
    data: ReviewInputs = FULL,
    res: Resolution = OWNER,
    limiter: Limiter | None = None,
    kicker: FakeTaskKicker | None = None,
) -> tuple[AppReviewService, Repo, FakeConsents]:
    repo = Repo()
    consents = FakeConsents({STUDENT: frozenset({AI} if consent else set())})

    async def quota(_: UUID) -> int | None:
        return 3

    svc = AppReviewService(
        repo,
        Inputs(data),
        Access(res),  # type: ignore[arg-type]
        ai or Ai(),
        consents,
        FixedClock(NOW),
        limiter or Limiter(),  # type: ignore[arg-type]
        quota,
        BuiltinPrompts(),
        kicker or FakeTaskKicker(),
    )
    return svc, repo, consents


CTX: Any = SimpleNamespace(user_id=STUDENT)


async def _done(svc: AppReviewService, repo: Repo) -> AppReview:
    review = await svc.start(CTX, "ru")
    await svc.run(review.id)
    return repo.rows[review.id]


async def test_fan_out_runs_seven_sections_then_the_lead() -> None:
    ai = Ai()
    kicker = FakeTaskKicker()
    svc, repo, _ = _svc(ai=ai, kicker=kicker)
    queued = await svc.start(CTX, "ru")
    assert queued.status == "queued" and queued.version == 1
    assert kicker.names() == ["admission.app_review"]
    await svc.run(queued.id)
    review = repo.rows[queued.id]
    tasks = [t for t, _ in ai.calls]
    assert sorted(tasks[:7]) == sorted(prompt.SECTION_TASKS.values())
    assert tasks[7] is LEAD and len(tasks) == 8
    assert all(
        u.startswith("<student_text>") and "Locale: ru" in u for _, u in ai.calls
    )
    assert review.status == "done" and review.models == ["m-lead", "m-section"]
    assert [s["key"] for s in review.sections] == list(prompt.SECTION_KEYS)
    assert review.sections[1]["findings"][0]["evidence"] == ["item:1"]


async def test_sections_are_saved_as_each_one_finishes() -> None:
    svc, repo, _ = _svc(ai=Ai())
    await _done(svc, repo)
    running = [n for status, n in repo.snapshots if status == "running"]
    assert running[-len(prompt.SECTION_KEYS) :] == list(
        range(1, len(prompt.SECTION_KEYS) + 1)
    )


async def test_lead_merge_is_cleaned_sorted_and_scores_every_section() -> None:
    svc, repo, _ = _svc()
    report = (await _done(svc, repo)).report
    assert report is not None
    assert "<" not in report["headline"] and report["headline"].startswith("Strong")
    assert [a["priority"] for a in report["next_actions"]] == [1, 3]
    assert [s["section"] for s in report["section_scores"]] == list(prompt.SECTION_KEYS)
    assert report["fallback"] is False


async def test_section_without_data_is_skipped_without_a_call() -> None:
    ai = Ai()
    svc, repo, _ = _svc(ai=ai, data=dataclasses.replace(FULL, essays=[]))
    review = await _done(svc, repo)
    assert AiTask.ADMIT_APP_REVIEW_ESSAYS not in [t for t, _ in ai.calls]
    assert {s["key"]: s["status"] for s in review.sections}["essays"] == "skipped"


async def test_one_failed_section_degrades_gracefully() -> None:
    ai = Ai(fail={AiTask.ADMIT_APP_REVIEW_ACADEMICS})
    svc, repo, _ = _svc(ai=ai)
    review = await _done(svc, repo)
    assert review.status == "done"
    status = {s["key"]: s["status"] for s in review.sections}
    assert status["academics"] == "failed" and status["profile"] == "done"
    scores = {s["section"]: s["score"] for s in (review.report or {})["section_scores"]}
    assert scores["academics"] == 0


async def test_lead_failure_falls_back_to_a_deterministic_merge() -> None:
    svc, repo, _ = _svc(ai=Ai(fail={LEAD}))
    review = await _done(svc, repo)
    report = review.report or {}
    assert review.status == "done" and report["fallback"] is True
    assert report["overall_score"] == 60
    by = {p["section"]: p["evidence"] for p in report["strengths"]}
    assert by["activities"] == ["item:1"] and by["profile"] == []


async def test_all_sections_failing_fails_the_review() -> None:
    svc, repo, _ = _svc(ai=Ai(fail=set(prompt.SECTION_TASKS.values())))
    review = await _done(svc, repo)
    assert review.status == "failed" and review.error_code == "sections_failed"


async def test_consent_is_required_to_start_and_rechecked_by_the_job() -> None:
    ai = Ai()
    svc, _, _ = _svc(ai=ai, consent=False)
    with pytest.raises(ConsentRequiredError):
        await svc.start(CTX, "en")
    svc, repo, consents = _svc(ai=ai)
    queued = await svc.start(CTX, "en")
    consents.grants[STUDENT] = frozenset()
    await svc.run(queued.id)
    assert repo.rows[queued.id].status == "failed"
    assert repo.rows[queued.id].error_code == "consent_required"
    assert ai.calls == []


async def test_conflict_while_one_is_active_and_weekly_quota() -> None:
    svc, repo, _ = _svc(limiter=Limiter(allow=1))
    first = await svc.start(CTX, "en")
    with pytest.raises(AdmissionConflictError):
        await svc.start(CTX, "en")
    await svc.run(first.id)
    with pytest.raises(RateLimitedError):
        await svc.start(CTX, "en")


async def test_only_the_owner_starts() -> None:
    svc, _, _ = _svc(res=Resolution(permissions=frozenset(), in_scope=True))
    with pytest.raises(AdmissionForbiddenError):
        await svc.start(CTX, "en")


async def test_staff_need_full_permissions_and_see_only_shared_versions() -> None:
    svc, repo, _ = _svc()
    done = await _done(svc, repo)
    hidden = await svc.start(CTX, "en")
    repo.rows[hidden.id].status = "done"
    repo.rows[hidden.id].staff_visible = False
    staff_ctx: Any = SimpleNamespace(user_id=COUNSELOR)
    full = frozenset(Permission)
    svc._access = Access(Resolution(permissions=full, in_scope=True))  # type: ignore
    assert [r.id for r in await svc.staff_list(staff_ctx, STUDENT)] == [done.id]
    with pytest.raises(AdmissionNotFoundError):
        await svc.staff_get(staff_ctx, STUDENT, hidden.id)
    mentor = Resolution(permissions=full - {Permission.NOTES_STAFF}, in_scope=True)
    svc._access = Access(mentor)  # type: ignore
    with pytest.raises(AdmissionForbiddenError):
        await svc.staff_list(staff_ctx, STUDENT)
    svc._access = Access(Resolution(full, in_scope=True, limited=True))  # type: ignore
    with pytest.raises(AdmissionForbiddenError):
        await svc.staff_list(staff_ctx, STUDENT)


async def test_partial_sections_are_visible_mid_run_with_states() -> None:
    svc, repo, _ = _svc()
    review = await svc.start(CTX, "ru")
    assert [s["status"] for s in review.section_states()] == ["pending"] * 7
    review.status = "running"
    review.sections = [{"key": "profile", "status": "done", "score": 5}]
    states = review.section_states()
    assert [s["key"] for s in states] == list(prompt.SECTION_KEYS)
    assert states[0]["status"] == "done"
    assert {s["status"] for s in states[1:]} == {"running"}
    got = await svc.get_mine(CTX, review.id)
    assert got.section_states()[0]["score"] == 5
    from app.interfaces.http.v1.admission.routes_app_review import AppReviewOut

    out = AppReviewOut.of(got)
    assert [s.status for s in out.sections][:2] == ["done", "running"]

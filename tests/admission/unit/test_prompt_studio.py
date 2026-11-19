"""Prompt studio: permission, validation, testing and versioning."""

from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.prompt_studio import SampleInput
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes_prompt_studio import BAD, Studio
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign

import pytest

TASK = "admit_essay_review"
SAMPLE = SampleInput(text="My essay text.")


async def _counselor() -> tuple[Studio, AdmissionContext]:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    return Studio(w.store), await w.ctx(STAFF, Role.COUNSELOR)


async def test_student_is_forbidden() -> None:
    """ADM-PST-001 a student cannot open the studio."""
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await Studio(w.store).service.slots(ctx)


async def test_mentor_without_grant_is_forbidden() -> None:
    """ADM-PST-002 an essay mentor lacks essay_prompts:edit."""
    w = World()
    w.store.assignments[STAFF] = (_assign("essay_mentor", "all", None),)
    ctx = await w.ctx(STAFF, Role.TEACHER)
    with pytest.raises(AdmissionForbiddenError):
        await Studio(w.store).service.slot(ctx, TASK, "base", "")


async def test_counselor_and_admin_may_edit() -> None:
    """ADM-PST-003 counselor_full and administrators pass."""
    s, ctx = await _counselor()
    assert s.service.can_edit(ctx)
    w = World()
    admin = await w.ctx(new_id(), Role.ADMIN)
    assert Studio(w.store).service.can_edit(admin)


async def test_unknown_slot_is_not_found() -> None:
    """ADM-PST-004 only the four whitelisted slots exist."""
    s, ctx = await _counselor()
    with pytest.raises(AdmissionNotFoundError):
        await s.service.slot(ctx, "admit_essay_coach", "brainstorm", "")


async def test_invalid_draft_makes_no_model_call() -> None:
    """ADM-PST-005 a blocking issue answers 422 before any run."""
    s, ctx = await _counselor()
    with pytest.raises(ValidationFailedError):
        await s.service.test(ctx, TASK, "base", text=BAD, samples=[SAMPLE], locale="en")
    assert s.runner.calls == 0


async def test_three_samples_run_twice_each() -> None:
    """ADM-PST-006 three samples cost six runs and show the delta."""
    s, ctx = await _counselor()
    report = await s.service.test(
        ctx, TASK, "base", text="draft", samples=[SAMPLE] * 3, locale="en"
    )
    assert s.runner.calls == 6
    assert report.results[0].delta.score_delta == 10
    assert [w.code for w in report.warnings] == ["missing_fairness"]


async def test_four_samples_refused() -> None:
    """ADM-PST-007 at most three samples."""
    s, ctx = await _counselor()
    with pytest.raises(ValidationFailedError):
        await s.service.test(
            ctx, TASK, "base", text="draft", samples=[SAMPLE] * 4, locale="en"
        )
    assert s.runner.calls == 0


async def test_uni_slot_needs_institution() -> None:
    """ADM-PST-008 the uni slot is tested against one university."""
    s, ctx = await _counselor()
    with pytest.raises(ValidationFailedError):
        await s.service.test(
            ctx,
            "admit_essay_uni_review",
            "uni",
            text="draft",
            samples=[SAMPLE],
            locale="en",
        )
    with pytest.raises(AdmissionNotFoundError):
        await s.service.test(
            ctx,
            "admit_essay_uni_review",
            "uni",
            text="draft",
            samples=[SAMPLE],
            locale="en",
            institution_id=UUID(int=0),
        )
    assert s.runner.calls == 0


async def test_thirty_runs_then_limited() -> None:
    """ADM-PST-009 30 sample runs a day, the 31st answers 429."""
    s, ctx = await _counselor()
    for _ in range(10):
        await s.service.test(
            ctx, TASK, "base", text="draft", samples=[SAMPLE] * 3, locale="en"
        )
    calls = s.runner.calls
    with pytest.raises(RateLimitedError):
        await s.service.test(
            ctx, TASK, "base", text="draft", samples=[SAMPLE], locale="en"
        )
    assert s.runner.calls == calls


async def test_missing_exemplar_is_not_found() -> None:
    """ADM-PST-010 an unknown exemplar id answers 404 and costs nothing."""
    s, ctx = await _counselor()
    with pytest.raises(AdmissionNotFoundError):
        await s.service.test(
            ctx,
            TASK,
            "base",
            text="draft",
            samples=[SampleInput(exemplar_id=new_id())],
            locale="en",
        )
    assert s.limiter.count == 0
    known = new_id()
    s.exemplars.add(known)
    report = await s.service.test(
        ctx,
        TASK,
        "base",
        text="draft",
        samples=[SampleInput(exemplar_id=known)],
        locale="en",
    )
    assert report.results[0].exemplar_id == known


async def test_sample_needs_exactly_one_source() -> None:
    """ADM-PST-011 text and exemplar_id are exclusive; text is capped."""
    s, ctx = await _counselor()
    for bad in (
        SampleInput(),
        SampleInput(text="x", exemplar_id=new_id()),
        SampleInput(text="x" * 20_001),
    ):
        with pytest.raises(ValidationFailedError):
            await s.service.test(
                ctx, TASK, "base", text="draft", samples=[bad], locale="en"
            )


async def test_writes_carry_the_actor() -> None:
    """ADM-PST-012 save, activate and revert delegate with the caller."""
    s, ctx = await _counselor()
    saved = await s.service.save(ctx, TASK, "base", text="new", locale="en", note="n")
    assert [w.code for w in saved.warnings] == ["missing_fairness"]
    await s.service.activate(ctx, TASK, "base", 2)
    await s.service.revert(ctx, TASK, "base", "en")
    assert [(c[0], c[1]) for c in s.admin.calls] == [
        ("put", ctx.actor),
        ("activate", ctx.actor),
        ("revert", ctx.actor),
    ]
    with pytest.raises(ValidationFailedError):
        await s.service.save(ctx, TASK, "base", text=BAD, locale="", note="")
    assert len(s.admin.calls) == 3

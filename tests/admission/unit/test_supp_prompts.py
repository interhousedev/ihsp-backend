"""Supplemental prompts: year-over-year diff, curator edits, errors and audit."""

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.application.supp_prompts import SuppPromptService
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.supp_prompts import (
    SuppPrompt,
    diff_cycle,
    history,
    previous_cycle,
    valid_cycle,
)
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign
from tests.fakes.clock import FixedClock

import pytest


def _p(pos: int, text: str, limit: int | None = 250) -> SuppPrompt:
    return SuppPrompt(pos, text, limit, True, "https://example.edu/apply")


def test_cycle_format_and_previous() -> None:
    assert valid_cycle("2025-26")
    assert valid_cycle("2099-00")
    assert not valid_cycle("2025-27")
    assert not valid_cycle("abc")
    assert previous_cycle("2025-26") == "2024-25"


def test_diff_marks_same_changed_new_removed() -> None:
    old = [_p(0, "Why us?"), _p(1, "Describe a community."), _p(2, "Old prompt.")]
    new = [
        _p(0, "  why   US? "),
        _p(1, "Describe a community you belong to."),
        _p(2, "Old prompt."),
        _p(3, "A brand new question."),
    ]
    out = diff_cycle(new, old)
    assert [c.status for c in out] == ["same", "changed", "same", "new"]
    assert out[1].previous_text == "Describe a community."
    removed = diff_cycle([_p(0, "Why us?")], old)
    assert [c.status for c in removed] == ["same", "removed", "removed"]


def test_history_without_previous_cycle_is_all_new() -> None:
    cycles = history({"2025-26": [_p(0, "Changed.")], "2024-25": [_p(0, "Original.")]})
    assert [c.cycle for c in cycles] == ["2025-26", "2024-25"]
    assert cycles[0].prompts[0].status == "changed"
    assert cycles[1].prompts[0].status == "new"


def _svc(w: World) -> SuppPromptService:
    curators = CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW))
    return SuppPromptService(lambda: FakeUow(w.store), curators.can_review)


async def _curator(w: World) -> AdmissionContext:
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    return await w.ctx(STAFF, Role.COUNSELOR)


async def test_staff_replaces_cycle_and_is_audited() -> None:
    w = World()
    inst = new_id()
    w.store.known_targets.add(inst)
    ctx = await _curator(w)
    await _svc(w).replace(ctx, inst, "2024-25", [_p(0, "Why us?")])
    out = await _svc(w).replace(
        ctx, inst, "2025-26", [_p(7, " Why us? "), _p(9, "New one", None)]
    )
    assert [c.cycle for c in out] == ["2025-26", "2024-25"]
    assert [p.prompt.position for p in out[0].prompts] == [0, 1]
    assert [p.status for p in out[0].prompts] == ["same", "new"]
    assert w.store.audit[-1].action == "catalog.supp_prompts_replaced"
    assert w.store.audit[-1].meta == {"cycle": "2025-26", "count": 2}
    student = await w.ctx(STUDENT, Role.STUDENT)
    assert [c.cycle for c in await _svc(w).cycles(inst)] == ["2025-26", "2024-25"]
    assert student.user_id == STUDENT


async def test_student_cannot_replace() -> None:
    w = World()
    inst = new_id()
    w.store.known_targets.add(inst)
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await _svc(w).replace(ctx, inst, "2025-26", [_p(0, "x")])
    assert w.store.audit == []


@pytest.mark.parametrize("role", [Role.TEACHER, Role.COUNSELOR])
async def test_replace_needs_a_live_curate_grant(role: Role) -> None:
    w = World()
    inst = new_id()
    w.store.known_targets.add(inst)
    ctx = await w.ctx(STAFF, role)
    with pytest.raises(AdmissionForbiddenError):
        await _svc(w).replace(ctx, inst, "2025-26", [_p(0, "x")])
    assert w.store.audit == []


async def test_admin_replaces_without_a_grant() -> None:
    w = World()
    inst = new_id()
    w.store.known_targets.add(inst)
    ctx = await w.ctx(STAFF, Role.ADMIN)
    await _svc(w).replace(ctx, inst, "2025-26", [_p(0, "x")])
    assert w.store.audit[-1].action == "catalog.supp_prompts_replaced"


async def test_unknown_institution_is_404() -> None:
    w = World()
    ctx = await w.ctx(STAFF, Role.ADMIN)
    with pytest.raises(AdmissionNotFoundError):
        await _svc(w).cycles(new_id())
    with pytest.raises(AdmissionNotFoundError):
        await _svc(w).replace(ctx, new_id(), "2025-26", [_p(0, "x")])


@pytest.mark.parametrize(
    ("cycle", "prompt", "field"),
    [
        ("2025-27", _p(0, "ok"), "cycle"),
        ("abc", _p(0, "ok"), "cycle"),
        ("2025-26", _p(0, "   "), "prompt"),
        ("2025-26", _p(0, "ok", 0), "word_limit"),
        ("2025-26", SuppPrompt(0, "ok", None, True, "http://x.edu"), "source_url"),
    ],
)
async def test_invalid_input_is_422(cycle: str, prompt: SuppPrompt, field: str) -> None:
    w = World()
    inst = new_id()
    w.store.known_targets.add(inst)
    ctx = await _curator(w)
    with pytest.raises(ValidationFailedError) as err:
        await _svc(w).replace(ctx, inst, cycle, [prompt])
    assert err.value.params == {"field": field}

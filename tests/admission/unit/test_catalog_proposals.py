"""Catalog proposals: who may propose and review, and what approval does."""

from typing import Any

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidProofUrlError,
    InvalidTransitionError,
)
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign
from tests.fakes.clock import FixedClock

import pytest

URL = "https://example.edu/admissions"
NEW = {"name": "Test University", "country": "GB"}


def _svc(w: World) -> CatalogProposalService:
    return CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW))


async def _propose(w: World, ctx: AdmissionContext, **kw: Any) -> Any:
    args = {"kind": "institution", "target_id": None, "fields": NEW}
    args |= {"source_url": URL, "note": None} | kw
    return await _svc(w).propose(ctx, **args)


async def _curator(w: World) -> AdmissionContext:
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    return await w.ctx(STAFF, Role.COUNSELOR)


async def test_curator_reviews_and_approval_applies() -> None:
    w = World()
    ctx = await _curator(w)
    p = await _propose(w, ctx)
    done = await _svc(w).review(
        ctx, p.id, approve=True, note="ok", lock_version=p.lock_version
    )
    assert done.status == "approved" and done.reviewed_by == STAFF
    assert [a.id for a in w.store.applied] == [p.id]
    assert w.store.audit[-1].action == "catalog.proposal_approved"


async def test_reject_does_not_apply() -> None:
    w = World()
    ctx = await _curator(w)
    p = await _propose(w, ctx)
    done = await _svc(w).review(ctx, p.id, approve=False, note=None, lock_version=0)
    assert done.status == "rejected" and w.store.applied == []


async def test_admin_reviews_without_assignment() -> None:
    w = World()
    ctx = await w.ctx(STAFF, Role.ADMIN)
    assert _svc(w).can_review(ctx)
    p = await _propose(w, ctx)
    await _svc(w).review(ctx, p.id, approve=True, note=None, lock_version=0)


async def test_mentor_proposes_but_cannot_review() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("essay_mentor", "all", None),)
    ctx = await w.ctx(STAFF, Role.MENTOR)
    p = await _propose(w, ctx)
    with pytest.raises(AdmissionForbiddenError):
        await _svc(w).review(ctx, p.id, approve=True, note=None, lock_version=0)
    assert [x.id for x in await _svc(w).list(ctx, status=None)] == [p.id]


async def test_student_cannot_propose() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await _propose(w, ctx)


async def test_non_https_url_is_rejected() -> None:
    w = World()
    ctx = await _curator(w)
    with pytest.raises(InvalidProofUrlError):
        await _propose(w, ctx, source_url="http://example.edu")


async def test_new_row_needs_required_fields() -> None:
    w = World()
    ctx = await _curator(w)
    with pytest.raises(ValidationFailedError):
        await _propose(w, ctx, fields={"name": "X"})
    with pytest.raises(ValidationFailedError):
        await _propose(w, ctx, fields={"unknown": "X"})


async def test_edit_needs_existing_target_but_not_all_fields() -> None:
    w = World()
    ctx = await _curator(w)
    target = new_id()
    with pytest.raises(AdmissionNotFoundError):
        await _propose(w, ctx, target_id=target, fields={"city": "Leeds"})
    w.store.known_targets.add(target)
    p = await _propose(w, ctx, target_id=target, fields={"city": "Leeds"})
    assert p.payload == {"city": "Leeds"}


async def test_double_review_and_stale_lock() -> None:
    w = World()
    ctx = await _curator(w)
    p = await _propose(w, ctx)
    with pytest.raises(AdmissionConflictError):
        await _svc(w).review(ctx, p.id, approve=True, note=None, lock_version=5)
    await _svc(w).review(ctx, p.id, approve=True, note=None, lock_version=0)
    with pytest.raises(InvalidTransitionError):
        await _svc(w).review(ctx, p.id, approve=False, note=None, lock_version=1)

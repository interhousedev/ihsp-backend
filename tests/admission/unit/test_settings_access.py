"""Admission settings: administrators and live counselors edit, others do not."""

from app.modules.admission.application.actor import can_edit_settings
from app.modules.admission.application.career import CareerService
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign
from tests.fakes.clock import FixedClock

import pytest


def _career(w: World) -> CareerService:
    return CareerService(
        lambda: FakeUow(w.store), w.policy, FixedClock(NOW)  # type: ignore
    )


async def test_admin_and_counselor_may_edit() -> None:
    w = World()
    assert can_edit_settings(await w.ctx(new_id(), Role.ADMIN), NOW)
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    assert can_edit_settings(await w.ctx(STAFF, Role.COUNSELOR), NOW)
    _career(w).require_editor(await w.ctx(STAFF, Role.COUNSELOR))


@pytest.mark.parametrize(
    ("key", "role"),
    [
        ("student_counselor", Role.MENTOR),
        ("transcript_officer", Role.TRANSCRIPT_OFFICER),
    ],
)
async def test_mentor_and_officer_refused(key: str, role: Role) -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign(key, "all", None),)
    ctx = await w.ctx(STAFF, role)
    assert not can_edit_settings(ctx, NOW)
    with pytest.raises(AdmissionForbiddenError):
        _career(w).require_editor(ctx)


async def test_student_and_counselor_without_assignment_refused() -> None:
    w = World()
    with pytest.raises(AdmissionForbiddenError):
        _career(w).require_editor(await w.ctx(STUDENT, Role.STUDENT))
    assert not can_edit_settings(await w.ctx(STAFF, Role.COUNSELOR), NOW)

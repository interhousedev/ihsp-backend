"""Entitlement: implicit for eligible grades, a stored row wins."""

from app.modules.admission.application.actor import effective_entitlement
from app.modules.admission.domain.access import Entitlement
from app.modules.admission.domain.entitlement import (
    AdmissionActor,
    grade_from_group_name,
)
from app.shared.actor import Role
from app.shared.contracts.academic import StudentRef
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, student_ref

import pytest

USER = new_id()


@pytest.mark.parametrize(
    ("name", "grade"), [("10-A", 10), ("11B", 11), ("9-V", 9), ("", None), (None, None)]
)
def test_grade_from_group_name(name: str | None, grade: int | None) -> None:
    assert grade_from_group_name(name) == grade


def _eff(
    stored: Entitlement | None, ref: StudentRef | None, *, student: bool = False
) -> Entitlement | None:
    return effective_entitlement(
        stored, ref, {10, 11}, NOW, student_role=student, user_id=USER
    )


def test_eligible_group_is_implicitly_entitled() -> None:
    ent = _eff(None, student_ref(USER, new_id(), "11-A"))
    assert ent is not None and ent.kind == "school_student" and ent.is_applicant


def test_ineligible_grade_and_no_group_without_student_role() -> None:
    ref = student_ref(USER, new_id(), "9-A")
    assert _eff(None, ref) is None
    assert _eff(None, None) is None


def test_student_role_stacks_over_group_and_grade() -> None:
    for ref in (None, student_ref(USER, new_id(), "9-A")):
        ent = _eff(None, ref, student=True)
        assert ent is not None and ent.is_applicant and ent.user_id == USER


def test_revoked_row_wins_even_with_student_role() -> None:
    revoked = Entitlement(USER, "school_student", None, None, NOW, revoked_at=NOW)
    ref = student_ref(USER, new_id(), "11-A")
    for student in (False, True):
        ent = _eff(revoked, ref, student=student)
        assert ent is revoked and not ent.is_applicant


def test_actor_kinds() -> None:
    ent = Entitlement(USER, "alumni", 2025, None, NOW)
    assert AdmissionActor(USER, ent, frozenset()).kind == "applicant"
    staff = AdmissionActor(USER, None, frozenset({Role.COUNSELOR}))
    assert staff.kind == "staff" and staff.may_enter
    nobody = AdmissionActor(USER, None, frozenset())
    assert nobody.kind == "none" and not nobody.may_enter

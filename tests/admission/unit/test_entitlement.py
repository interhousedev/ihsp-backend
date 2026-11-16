"""Entitlement: implicit for eligible grades, a stored row wins."""

from app.modules.admission.application.actor import effective_entitlement
from app.modules.admission.domain.access import Entitlement
from app.modules.admission.domain.entitlement import (
    AdmissionActor,
    grade_from_group_name,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, student_ref

import pytest

USER = new_id()


@pytest.mark.parametrize(
    ("name", "grade"), [("10-A", 10), ("11B", 11), ("9-V", 9), ("", None), (None, None)]
)
def test_grade_from_group_name(name: str | None, grade: int | None) -> None:
    assert grade_from_group_name(name) == grade


def test_eligible_student_is_implicitly_entitled() -> None:
    ent = effective_entitlement(
        None, student_ref(USER, new_id(), "11-A"), {10, 11}, NOW
    )
    assert ent is not None and ent.kind == "school_student" and ent.is_applicant


def test_ineligible_grade_and_non_student() -> None:
    ref = student_ref(USER, new_id(), "9-A")
    assert effective_entitlement(None, ref, {10, 11}, NOW) is None
    assert effective_entitlement(None, None, {10, 11}, NOW) is None


def test_stored_row_wins_even_when_revoked() -> None:
    revoked = Entitlement(USER, "school_student", None, None, NOW, revoked_at=NOW)
    ref = student_ref(USER, new_id(), "11-A")
    ent = effective_entitlement(revoked, ref, {10, 11}, NOW)
    assert ent is revoked and not ent.is_applicant


def test_actor_kinds() -> None:
    ent = Entitlement(USER, "alumni", 2025, None, NOW)
    assert AdmissionActor(USER, ent, frozenset(), False).kind == "applicant"
    staff = AdmissionActor(USER, None, frozenset({Role.COUNSELOR}), False)
    assert staff.kind == "staff" and staff.may_enter
    helper = AdmissionActor(USER, None, frozenset(), True)
    assert helper.helper_only and helper.may_enter
    nobody = AdmissionActor(USER, None, frozenset(), False)
    assert nobody.kind == "none" and not nobody.may_enter
    blocked = AdmissionActor(USER, ent, frozenset(), False, blocked=True)
    assert blocked.kind == "none"

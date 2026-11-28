"""Admission server scopes: applicant vs staff, presets and old personal tokens."""

from app.modules.identity.domain.scopes import (
    PRESETS,
    SCOPE_CATALOG,
    app_scopes_for_roles,
    role_may_use_server,
    scope_names,
    scopes_for_roles,
    server_from_audience,
)
from app.shared.actor import Role
from app.shared.mcp_scopes import PAT_SCOPE_ALIASES, pat_scopes

STAFF = {"caseload:read", "students:read", "students:write", "documents:review"}


def test_admission_is_a_server_with_its_audience() -> None:
    assert server_from_audience("mcp-admission") == "admission"
    assert role_may_use_server({Role.STUDENT}, "admission")
    assert role_may_use_server({Role.COUNSELOR}, "admission")
    assert not role_may_use_server({Role.TEACHER}, "admission")
    assert STAFF <= scope_names("admission")


def test_a_student_is_offered_applicant_scopes_and_staff_only_staff_ones() -> None:
    student = scopes_for_roles("admission", {Role.STUDENT})
    counselor = scopes_for_roles("admission", {Role.COUNSELOR})

    assert not student & STAFF
    assert "application:read" in student
    assert counselor == STAFF | {"catalog:read"}


def test_staff_scopes_are_in_no_preset() -> None:
    for preset in PRESETS["admission"]:
        assert not set(preset.scopes) & STAFF
    for preset in PRESETS["app"]:
        assert not set(preset.scopes) & {f"admission:{s}" for s in STAFF}


def test_a_student_never_gets_staff_scopes_on_app() -> None:
    every = frozenset(info.scope for info in SCOPE_CATALOG["app"])
    student = app_scopes_for_roles(every, {Role.STUDENT})
    mentor = app_scopes_for_roles(every, {Role.MENTOR})

    assert not student & {f"admission:{s}" for s in STAFF}
    assert "admission:application:read" in student
    assert {f"admission:{s}" for s in STAFF} <= mentor
    assert "admission:application:read" not in mentor


def test_personal_token_aliases_never_yield_staff_scopes() -> None:
    granted = pat_scopes(PAT_SCOPE_ALIASES)

    assert not granted & STAFF
    assert granted <= scope_names("admission")
    assert pat_scopes({"admission:catalog", "unknown"}) == frozenset()

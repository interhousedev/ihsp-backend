"""The staff access matrix over real HTTP and PostgreSQL.

An assigned counselor reads list, tasks, documents and the profile frame without
the student's consent; essays, words and profile answers need `staff_view`.
"""

from app.modules.admission.domain.permissions import KIND_ALLOW_LIST
from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.admission.ports.consent import STAFF_VIEW
from app.modules.legal.infrastructure.purpose_consents import SqlPurposeConsents
from app.shared.ids import new_id
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

BASE = "/v1/admission"


def _role() -> StaffRoleRow:
    return StaffRoleRow(
        id=new_id(),
        key=None,
        kind="counselor",
        name="Counselor test",
        name_i18n={},
        permissions=sorted(p.value for p in KIND_ALLOW_LIST["counselor"]),
        is_builtin=False,
    )


BASE = "/v1/admission"


async def test_counselor_access_matrix(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    from app.shared.actor import Role

    container, client, switch, student = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "acc.student"
    )
    mine = await _user(container, "acc.counselor", Role.COUNSELOR)
    other = await _user(container, "acc.counselor2", Role.COUNSELOR)
    async with container.sessionmaker() as session, session.begin():
        session.add(
            EntitlementRow(
                user_id=student.user_id,
                kind="school_student",
                cohort_year=None,
                granted_by=None,
            )
        )
        role = _role()
        session.add(role)
        await session.flush()
        session.add(
            StaffAssignmentRow(
                id=new_id(),
                user_id=mine.user_id,
                staff_role_id=role.id,
                scope_kind="student",
                scope_ref=student.user_id,
                starts_at=container.clock.now(),
                granted_by=None,
                granted_via="admin",
            )
        )
    sid = student.user_id
    async with client:
        made = await client.post(f"{BASE}/essays", json={"prompt_text": "Why?"})
        assert made.status_code in (200, 201), made.text
        saved = await client.put(
            f"{BASE}/me/profile", json={"answers": {"q32": "5k_15k"}}
        )
        assert saved.status_code == 200, saved.text

        switch.set(mine)
        for path in (f"/students/{sid}/tasks", f"/students/{sid}/list"):
            r = await client.get(BASE + path)
            assert r.status_code == 200, (path, r.text)
        prof = await client.get(f"{BASE}/students/{sid}/profile")
        assert prof.status_code == 200, prof.text
        assert prof.json()["answers"] == {}
        for path in (f"/students/{sid}/essays", f"/students/{sid}/words"):
            r = await client.get(BASE + path)
            assert r.status_code == 403, (path, r.text)

        switch.set(other)
        for path in (f"/students/{sid}/tasks", f"/students/{sid}/profile"):
            r = await client.get(BASE + path)
            assert r.status_code == 404, (path, r.text)

        await SqlPurposeConsents(container.sessionmaker).grant(
            sid, STAFF_VIEW, now=container.clock.now()
        )
        switch.set(mine)
        assert (await client.get(f"{BASE}/students/{sid}/essays")).status_code == 200


async def test_counselor_task_carries_the_assigner_name(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    from app.shared.actor import Role

    container, client, switch, student = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "acc.student2"
    )
    mine = await _user(container, "acc.counselor3", Role.COUNSELOR)
    async with container.sessionmaker() as session, session.begin():
        session.add(
            EntitlementRow(
                user_id=student.user_id,
                kind="school_student",
                cohort_year=None,
                granted_by=None,
            )
        )
        role = _role()
        session.add(role)
        await session.flush()
        session.add(
            StaffAssignmentRow(
                id=new_id(),
                user_id=mine.user_id,
                staff_role_id=role.id,
                scope_kind="student",
                scope_ref=student.user_id,
                starts_at=container.clock.now(),
                granted_by=None,
                granted_via="admin",
            )
        )
    async with client:
        switch.set(mine)
        r = await client.post(
            f"{BASE}/staff/students/{student.user_id}/tasks", json={"title": "Plan"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["created_by"] == "counselor"
        assert r.json()["assigned_by_name"]
        switch.set(student)
        mine_tasks = (await client.get(f"{BASE}/tasks")).json()["items"]
        assert [t["assigned_by_name"] for t in mine_tasks] == [
            r.json()["assigned_by_name"]
        ]

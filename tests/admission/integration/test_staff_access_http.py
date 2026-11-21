"""The staff access matrix over real HTTP and PostgreSQL.

An assigned counselor reads list, tasks, documents and the profile frame without
the student's consent; essays, words and profile answers need `staff_view`.
"""

import datetime as dt
from uuid import UUID

from app.bootstrap.container import Container
from app.modules.admission.domain.permissions import KIND_ALLOW_LIST
from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.admission.ports.consent import FINANCE, STAFF_VIEW
from app.modules.legal.infrastructure.purpose_consents import SqlPurposeConsents
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _As,
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from httpx import AsyncClient

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


async def _world(
    make_container: ContainerFactory, cleaned: list[FastAPI], tag: str
) -> tuple[Container, AsyncClient, _As, Actor, Actor, UUID]:
    """A student with a profile, a counselor assigned to them, and the role id."""
    container, client, switch, student = await _http(
        make_container, cleaned, Role.STUDENT, f"{tag}.student"
    )
    counselor = await _user(container, f"{tag}.counselor", Role.COUNSELOR)
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
                user_id=counselor.user_id,
                staff_role_id=role.id,
                scope_kind="student",
                scope_ref=student.user_id,
                starts_at=container.clock.now(),
                granted_by=None,
                granted_via="admin",
            )
        )
    return container, client, switch, student, counselor, role.id


async def test_pin_shows_first_on_the_student_today(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, switch, student, counselor, _ = await _world(
        make_container, overrides_cleaned, "pin"
    )
    async with client:
        switch.set(counselor)
        url = f"{BASE}/staff/students/{student.user_id}/pin"
        bad = await client.post(
            url, json={"title": "x", "href": "https://evil.example"}
        )
        assert bad.status_code == 422, bad.text
        assert (await client.get(url)).status_code == 404
        ok = await client.post(
            url, json={"title": "Send the transcript", "href": "/tasks/"}
        )
        assert ok.status_code == 200, ok.text
        assert (await client.get(url)).json()["title"] == "Send the transcript"
        switch.set(student)
        top = (await client.get(f"{BASE}/today")).json()["next"][0]
        assert top["kind"] == "pinned" and top["title"] == "Send the transcript"
        assert top["pinned_by"]
        switch.set(counselor)
        assert (await client.delete(url)).status_code == 204
        switch.set(student)
        assert (await client.get(f"{BASE}/today")).json()["next"][0]["kind"] != "pinned"
        stranger = await _user(container, "pin.stranger", Role.COUNSELOR)
        switch.set(stranger)
        assert (await client.post(url, json={"title": "x"})).status_code == 404


async def test_budget_hidden_until_finance_consent(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, switch, student, counselor, _ = await _world(
        make_container, overrides_cleaned, "bud"
    )
    async with client:
        saved = await client.put(
            f"{BASE}/me/profile", json={"answers": {"q32": "5k_15k"}}
        )
        assert saved.status_code == 200, saved.text
        switch.set(counselor)
        url = f"{BASE}/students/{student.user_id}/profile"
        before = (await client.get(url)).json()
        assert before["budget_shared"] is False and before["family_budget"] is None
        await SqlPurposeConsents(container.sessionmaker).grant(
            student.user_id, FINANCE, now=container.clock.now()
        )
        after = (await client.get(url)).json()
        assert after["budget_shared"] is True and after["family_budget"] == "5k_15k"
        assert after["answers"] == {}


async def test_admin_lists_all_students_assigns_and_staff_see_deadlines(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, switch, student, counselor, role_id = await _world(
        make_container, overrides_cleaned, "adm"
    )
    admin = await _user(container, "adm.admin", Role.ADMIN)
    newcomer = await _user(container, "adm.counselor2", Role.COUNSELOR)
    async with client:
        saved = await client.put(f"{BASE}/me/profile", json={"answers": {}})
        assert saved.status_code == 200, saved.text
        listing = f"{BASE}/staff/students"
        switch.set(counselor)
        assert (await client.get(listing + "?scope=all")).status_code == 403
        mine = (await client.get(listing)).json()["items"]
        assert [i["student_id"] for i in mine] == [str(student.user_id)]
        made = await client.post(
            f"{BASE}/staff/students/{student.user_id}/tasks",
            json={
                "title": "Essay draft",
                "deadline": (container.clock.now() + dt.timedelta(days=10))
                .date()
                .isoformat(),
            },
        )
        assert made.status_code == 200, made.text

        switch.set(admin)
        rows = (await client.get(listing + "?scope=all&q=tester")).json()["items"]
        assert [r["student_id"] for r in rows] == [str(student.user_id)]
        assert [a["user_id"] for a in rows[0]["assigned_staff"]] == [
            str(counselor.user_id)
        ]
        assert (await client.get(listing + "?scope=all&q=zzzz")).json()["items"] == []
        given = await client.post(
            f"{BASE}/staff/assignments",
            json={
                "user_id": str(newcomer.user_id),
                "staff_role_id": str(role_id),
                "scope_kind": "student",
                "scope_ref": str(student.user_id),
            },
        )
        assert given.status_code == 201, given.text
        # An administrator reads no student content.
        assert (
            await client.get(f"{BASE}/students/{student.user_id}/tasks")
        ).status_code == 404

        switch.set(newcomer)
        assert len((await client.get(listing)).json()["items"]) == 1

        switch.set(counselor)
        due = (await client.get(f"{BASE}/staff/caseload-deadlines?scope=mine")).json()[
            "items"
        ]
        assert any(d["kind"] == "task" and d["by_staff"] for d in due)

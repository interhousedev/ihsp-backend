"""Readiness of a student for a counselor without the student's staff-view consent."""

from app.modules.admission.domain.essays import Essay
from app.modules.admission.domain.permissions import KIND_ALLOW_LIST
from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.essays_repository import SqlEssayRepository
from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "/v1/admission"


async def test_readiness_for_limited_student_is_without_the_essay_key(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, switch, student = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "rdy.student"
    )
    counselor = await _user(container, "rdy.counselor", Role.COUNSELOR)
    stranger = await _user(container, "rdy.counselor2", Role.COUNSELOR)
    async with container.sessionmaker() as session, session.begin():
        session.add(
            EntitlementRow(
                user_id=student.user_id,
                kind="school_student",
                cohort_year=None,
                granted_by=None,
            )
        )
        role = StaffRoleRow(
            id=new_id(),
            key=None,
            kind="counselor",
            name="Counselor test",
            name_i18n={},
            permissions=sorted(p.value for p in KIND_ALLOW_LIST["counselor"]),
            is_builtin=False,
        )
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
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        await s.commit()
        inst = (await s.execute(select(InstitutionRow).limit(1))).scalars().one().id
    # Sealed by another process: this one holds no key for the student's essays.
    async with container.sessionmaker() as session, session.begin():
        foreign = AesGcmEssayCipher(MemoryEssayKeyStore())
        await SqlEssayRepository(session, foreign).add(
            Essay(id=new_id(), student_id=student.user_id, title="T", body="B")
        )
    path = f"{BASE}/students/{student.user_id}/readiness"
    async with client:
        added = await client.post(f"{BASE}/list", json={"institution_id": str(inst)})
        assert added.status_code in (200, 201), added.text
        own = await client.get(f"{BASE}/readiness")
        assert own.status_code == 200, own.text
        switch.set(counselor)
        limited = await client.get(path)
        assert limited.status_code == 200, limited.text
        essays = [c for c in limited.json()["components"] if c["key"] == "essays"]
        assert essays and essays[0]["score"] > 0
        switch.set(stranger)
        assert (await client.get(path)).status_code == 404


async def test_essay_list_flags_a_row_that_does_not_open(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, _switch, student = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "unread.student"
    )
    async with container.sessionmaker() as session, session.begin():
        session.add(
            EntitlementRow(
                user_id=student.user_id,
                kind="school_student",
                cohort_year=None,
                granted_by=None,
            )
        )
    async with client:
        made = await client.post(f"{BASE}/essays", json={"title": "Mine"})
        assert made.status_code in (200, 201), made.text
        # A row sealed under a different key (tampered, or its key was lost).
        async with container.sessionmaker() as session, session.begin():
            foreign = AesGcmEssayCipher(MemoryEssayKeyStore())
            await SqlEssayRepository(session, foreign).add(
                Essay(id=new_id(), student_id=student.user_id, title="T", body="B")
            )
        listed = await client.get(f"{BASE}/essays")
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert sorted((e["title"], e["unreadable"]) for e in items) == [
            ("", True),
            ("Mine", False),
        ]

"""Courses catalogue and attached books over real HTTP and PostgreSQL."""

from app.modules.admission.domain.permissions import KIND_ALLOW_LIST
from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.library.infrastructure.orm import BookDetails
from app.modules.library.infrastructure.orm import Item as ItemRow
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

BASE = "/v1/admission"


def _item(title: str, status: str) -> ItemRow:
    return ItemRow(
        id=new_id(),
        slug=f"b-{new_id().hex[-10:]}",
        kind="book",
        type="textbook",
        title=title,
        author_label="Test Author",
        language="en",
        status=status,
        visibility="public",
        published_at=None,
    )


async def test_catalog_lists_books_and_counselor_attaches_for_student(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    """Search finds only published books; attach, student read, detach."""
    container, client, switch, student = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "bk.student"
    )
    counselor = await _user(container, "bk.counselor", Role.COUNSELOR)
    live, draft = _item("Zyxwv Orbit Atlas", "published"), _item("Zyxwv Draft", "draft")
    async with container.sessionmaker() as session, session.begin():
        session.add_all([live, draft])
        await session.flush()
        session.add_all(
            BookDetails(item_id=i.id, rights="official") for i in (live, draft)
        )
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
            name="Counselor books",
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
    mine = f"{BASE}/students/{student.user_id}/books"
    async with client:
        found = await client.get(
            f"{BASE}/courses/catalog", params={"q": "Zyxwv", "kind": "book"}
        )
        assert found.status_code == 200, found.text
        items = found.json()["items"]
        assert [i["id"] for i in items] == [str(live.id)]
        assert items[0]["kind"] == "book" and f"id={live.id}" in items[0]["url"]

        denied = await client.post(mine, json={"item_id": str(live.id)})
        assert denied.status_code == 403, denied.text

        switch.set(counselor)
        assert (
            await client.post(mine, json={"item_id": str(draft.id)})
        ).status_code == 404
        ok = await client.post(mine, json={"item_id": str(live.id), "note": "Read"})
        assert ok.status_code == 201, ok.text
        again = await client.post(mine, json={"item_id": str(live.id)})
        assert again.status_code == 201

        switch.set(student)
        got = await client.get(f"{BASE}/courses/books")
        assert got.status_code == 200, got.text
        assert [i["book"]["id"] for i in got.json()["items"]] == [str(live.id)]
        assert got.json()["items"][0]["note"] == "Read"

        switch.set(counselor)
        gone = await client.delete(f"{mine}/{live.id}")
        assert gone.status_code == 204, gone.text
        assert (await client.delete(f"{mine}/{live.id}")).status_code == 404
        switch.set(student)
        assert (await client.get(f"{BASE}/courses/books")).json()["items"] == []

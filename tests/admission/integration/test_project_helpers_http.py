"""Project helpers over real HTTP and PostgreSQL: curator CRUD, student read."""

from app.modules.admission.infrastructure.orm.access import EntitlementRow
from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

STAFF = "/v1/admission/staff/project-helpers"
HELPERS = "/v1/admission/projects/helpers"
IDEAS = "/v1/admission/projects/ideas"
BODY = {
    "kind": "organization",
    "name": "Tashkent maker space",
    "description": {"en": "Tools and a room", "ru": "", "uz": ""},
    "tags": ["product_dev", "website_tech"],
    "help_types": ["equipment_space"],
    "expertise_areas": ["3d printing"],
    "contacts": {
        "email": "maker@example.org",
        "phone": None,
        "telegram": None,
        "website": None,
    },
    "city": "Tashkent",
    "active": True,
}


async def test_curator_manages_helpers_and_student_reads_active_ones(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]  # noqa: F811
) -> None:
    """A curator adds and hides a helper; the student sees active matches only."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "ph.admin"
    )
    async with client:
        made = await client.post(STAFF, json=BODY)
        assert made.status_code == 201, made.text
        helper_id = made.json()["id"]
        bad = await client.post(
            STAFF, json={**BODY, "contacts": {"email": None, "phone": None}}
        )
        assert bad.status_code == 422, bad.text

        student = await _user(container, "ph.student", Role.STUDENT)
        async with container.sessionmaker() as session, session.begin():
            session.add(
                EntitlementRow(
                    user_id=student.user_id,
                    kind="school_student",
                    cohort_year=None,
                    granted_by=None,
                )
            )
        switch.set(student)
        found = await client.get(HELPERS, params=[("tag", "product_dev")])
        assert found.status_code == 200, found.text
        assert [h["id"] for h in found.json()["items"]] == [helper_id]
        assert (await client.get(STAFF)).status_code in (403, 404)
        assert (await client.post(STAFF, json=BODY)).status_code in (403, 404)
        empty = await client.get(IDEAS)
        assert empty.status_code == 200, empty.text
        assert empty.json() == {"latest": None, "history": []}

        switch.set(await _user(container, "ph.admin2", Role.ADMIN))
        hidden = await client.put(
            f"{STAFF}/{helper_id}", json={**BODY, "active": False}
        )
        assert hidden.status_code == 200, hidden.text
        assert len((await client.get(STAFF)).json()["items"]) == 1
        switch.set(student)
        assert (await client.get(HELPERS, params=[("tag", "product_dev")])).json()[
            "items"
        ] == []
        switch.set(await _user(container, "ph.admin3", Role.ADMIN))
        assert (await client.delete(f"{STAFF}/{helper_id}")).status_code == 204
        assert (await client.delete(f"{STAFF}/{helper_id}")).status_code == 404

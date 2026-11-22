"""Country facts over real HTTP and PostgreSQL: curator edit, student read."""

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

STAFF = "/v1/admission/staff/countries"
FACTS = "/v1/admission/country-facts"
BODY = {
    "as_of": "2026-11",
    "verified": False,
    "facts": {
        "safety": {
            "score": 4,
            "values": {"gpi_score": 1.5},
            "text": {"en": "Calm", "ru": "", "uz": ""},
            "sources": ["https://example.org/gpi"],
        }
    },
}


async def test_curator_edits_and_student_reads_marked_unverified(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]  # noqa: F811
) -> None:
    """A curator saves a draft; the student sees it unverified, then verified."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "cf.admin"
    )
    async with client:
        put = await client.put(f"{STAFF}/FR", json=BODY)
        assert put.status_code == 200, put.text
        bad = await client.put(
            f"{STAFF}/FR",
            json={**BODY, "facts": {"safety": {"score": 4, "values": {}}}},
        )
        assert bad.status_code == 422, bad.text
        listing = await client.get(STAFF, params={"status": "draft"})
        assert [i["country"] for i in listing.json()["items"]] == ["FR"]

        student = await _user(container, "cf.student", Role.STUDENT)
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
        got = await client.get(FACTS, params={"codes": "FR,JP"})
        assert got.status_code == 200, got.text
        items = got.json()["items"]
        assert [i["country"] for i in items] == ["FR"]
        assert items[0]["verified"] is False
        assert (await client.put(f"{STAFF}/FR", json=BODY)).status_code in (403, 404)

        switch.set(await _user(container, "cf.admin2", Role.ADMIN))
        assert (await client.post(f"{STAFF}/FR/verify")).json()["verified"] is True

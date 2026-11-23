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


async def test_new_fact_keys_and_student_country_routes(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]  # noqa: F811
) -> None:
    """Employers and salaries round-trip; the list and profile routes answer."""
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "cf.routes"
    )
    src = ["https://example.org/stats"]
    facts = {
        **BODY["facts"],  # type: ignore[dict-item]
        "employers": {
            "values": {"fields": {"cs_it": [{"name": "Acme", "sector": "Software"}]}},
            "sources": src,
        },
        "salaries": {
            "values": {
                "currency": "USD",
                "year": 2025,
                "overall_median_annual": 50000,
                "by_field": {"cs_it": 80000},
            },
            "sources": src,
        },
    }
    async with client:
        put = await client.put(f"{STAFF}/DE", json={**BODY, "facts": facts})
        assert put.status_code == 200, put.text
        assert (
            put.json()["facts"]["employers"]["values"]["fields"]["cs_it"][0]["name"]
            == "Acme"
        )
        eur = {
            **facts,
            "salaries": {"values": {"currency": "EUR", "year": 2025}, "sources": src},
        }
        bad = await client.put(f"{STAFF}/DE", json={**BODY, "facts": eur})
        assert bad.status_code == 422, bad.text

        listing = await client.get("/v1/admission/countries")
        assert listing.status_code == 200, listing.text
        de = next(i for i in listing.json()["items"] if i["country"] == "DE")
        assert de["region"] == "europe" and de["median_salary_usd"] == 50000
        assert de["scores"]["safety"] == 4

        got = await client.get(
            "/v1/admission/countries/de", params={"fields": "Computer Science"}
        )
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["highlight"] == ["cs_it"]
        assert body["facts"]["facts"]["salaries"]["values"]["by_field"] == {
            "cs_it": 80000
        }
        empty = await client.get("/v1/admission/countries/JP")
        assert empty.status_code == 200 and empty.json()["facts"] is None
        assert (await client.get("/v1/admission/countries/ZZ")).status_code == 404

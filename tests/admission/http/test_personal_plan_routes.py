"""Personal plan entries over real HTTP and PostgreSQL."""

from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

BASE = "/v1/admission/opportunities/plan"
FIND = {
    "kind": "event",
    "title": "Robotics camp",
    "url": "https://robots.example.org/camp",
    "registration_deadline": "2027-03-12",
}


async def test_personal_entry_lifecycle(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "pp.student"
    )
    other = await _user(container, "pp.other", Role.STUDENT)
    async with client:
        made = await client.post(f"{BASE}/personal", json=FIND)
        assert made.status_code == 201, made.text
        body = made.json()
        assert body["merged"] is False and body["entry"]["verified"] is False
        eid = body["entry"]["id"]

        dup = await client.post(f"{BASE}/personal", json=FIND)
        assert dup.status_code == 409, dup.text

        bad = await client.post(
            f"{BASE}/personal", json={**FIND, "url": "http://robots.example.org"}
        )
        assert bad.status_code == 422, bad.text

        plan = (await client.get(BASE)).json()
        assert [p["id"] for p in plan["personal"]] == [eid]

        upd = await client.patch(
            f"{BASE}/personal/{eid}",
            json={**FIND, "title": "Robotics camp 2027", "lock_version": 0},
        )
        assert upd.status_code == 200, upd.text
        stale = await client.patch(
            f"{BASE}/personal/{eid}", json={**FIND, "lock_version": 0}
        )
        assert stale.status_code == 409, stale.text

        switch.set(other)
        foreign = await client.delete(f"{BASE}/personal/{eid}")
        assert foreign.status_code == 404, foreign.text

        counselor = await _user(container, "pp.counselor", Role.COUNSELOR)
        switch.set(counselor)
        staff = await client.post(f"{BASE}/personal", json=FIND)
        assert staff.status_code == 403, staff.text


async def test_daily_limit_answers_429(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "pp.limit"
    )
    async with client:
        codes = [
            (
                await client.post(
                    f"{BASE}/personal", json={"kind": "event", "title": f"Camp {i}"}
                )
            ).status_code
            for i in range(21)
        ]
    assert codes[:20] == [201] * 20 and codes[20] == 429

"""`GET /calendar/export.ics` over real HTTP and PostgreSQL."""

import datetime as dt

from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    _user,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

BASE = "/v1/admission"


async def test_export_one_key_and_foreign_key(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "ics.student"
    )
    day = container.clock.now().date() + dt.timedelta(days=10)
    async with client:
        made = await client.post(
            f"{BASE}/opportunities/plan/personal",
            json={
                "kind": "event",
                "title": "Camp",
                "registration_deadline": day.isoformat(),
            },
        )
        assert made.status_code == 201, made.text
        key = f"personal:{made.json()['entry']['id']}:registration"

        r = await client.get(f"{BASE}/calendar/export.ics", params={"key": key})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/calendar")
        assert r.headers["cache-control"] == "no-store"
        assert r.text.count("BEGIN:VEVENT") == 1

        bad = await client.get(f"{BASE}/calendar/export.ics")
        assert bad.status_code == 422, bad.text

        switch.set(await _user(container, "ics.other", Role.STUDENT))
        foreign = await client.get(f"{BASE}/calendar/export.ics", params={"key": key})
        assert foreign.status_code == 404, foreign.text

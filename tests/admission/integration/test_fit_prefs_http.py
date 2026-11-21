"""Fit preferences, professions and ikigai over real HTTP and PostgreSQL."""

from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

BASE = "/v1/admission"


async def test_preferences_professions_and_ikigai_round_trip(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "fitstudent"
    )
    async with client:
        first = (await client.get(f"{BASE}/me/fit-preferences")).json()
        assert first["updated_at"] is None
        assert first["weights"] == {
            "afford": 0.25,
            "goals": 0.3,
            "profile": 0.3,
            "traits": 0.15,
        }
        ratings = {**first["ratings"], "price": 10, "salary": 1, "ai_resilience": 1}
        saved = await client.put(
            f"{BASE}/me/fit-preferences", json={"ratings": ratings}
        )
        assert saved.status_code == 200, saved.text
        body = (await client.get(f"{BASE}/me/fit-preferences")).json()
        assert body["ratings"]["price"] == 10 and body["updated_at"]
        assert abs(sum(body["weights"].values()) - 1) < 0.01
        assert body["weights"]["afford"] > body["weights"]["goals"]
        bad = await client.put(
            f"{BASE}/me/fit-preferences", json={"ratings": {**ratings, "price": 11}}
        )
        assert bad.status_code == 422

        found = await client.get(
            f"{BASE}/professions",
            params={"q": "программист"},
            headers={"Accept-Language": "ru"},
        )
        items = found.json()["items"]
        assert items and all(i["name"] and i["group"] for i in items)
        pid = items[0]["id"]
        uz = (
            await client.get(
                f"{BASE}/professions",
                params={"q": pid},
                headers={"Accept-Language": "uz"},
            )
        ).json()["items"]
        assert uz[0]["id"] == pid
        assert (await client.get(f"{BASE}/me/professions")).json() == {"items": []}
        put = await client.put(
            f"{BASE}/me/professions",
            json={"items": [{"profession_id": pid, "rank": 1}]},
        )
        assert put.status_code == 200, put.text
        assert [i["id"] for i in put.json()["items"]] == [pid]
        assert put.json()["items"][0]["rank"] == 1
        unknown = await client.put(
            f"{BASE}/me/professions",
            json={"items": [{"profession_id": "0000", "rank": 1}]},
        )
        assert unknown.status_code == 422

        assert (await client.get(f"{BASE}/me/ikigai")).json() == {
            "love": [],
            "good_at": [],
            "needs": [],
            "paid": [],
        }
        chips = {"love": ["chess", "Chess"], "good_at": ["math"]}
        ik = await client.put(f"{BASE}/me/ikigai", json=chips)
        assert ik.status_code == 200, ik.text
        assert ik.json()["love"] == ["chess"]
        long = await client.put(f"{BASE}/me/ikigai", json={"love": ["x" * 61]})
        assert long.status_code == 422
        assert (await client.get(f"{BASE}/me/ikigai")).json()["good_at"] == ["math"]

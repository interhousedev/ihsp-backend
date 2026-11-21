"""The Today feed over real HTTP and PostgreSQL."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI

TODAY = "/v1/admission/today"


async def test_today_feed_season_override_streak_and_deadline_rank(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "todaystudent"
    )
    async with client:
        first = (await client.get(TODAY, headers={"Accept-Language": "ru"})).json()
        assert first["season"]["source"] == "auto"
        assert first["season"]["key"] in {"explore", "choose"}
        assert first["streak"] == {"days": 0, "today_done": False, "last7": [False] * 7}
        assert 0 <= first["readiness"]["percent"] <= 100
        assert first["deadlines"] == []
        assert 1 <= len(first["next"]) <= 3
        assert all(
            n["href"].startswith("/") and n["minutes"] > 0 for n in first["next"]
        )
        assert all(c["label"] for c in first["season"]["checklist"])

        fixed = await client.put("/v1/admission/me/season", json={"key": "write"})
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["season"]["key"] == "write"
        assert fixed.json()["season"]["source"] == "override"
        assert (await client.get(TODAY)).json()["season"]["source"] == "override"
        bad = await client.put("/v1/admission/me/season", json={"key": "winter"})
        assert bad.status_code == 422
        back = await client.put("/v1/admission/me/season", json={"key": None})
        assert back.json()["season"]["source"] == "auto"

        soon = container.clock.now().astimezone(
            ZoneInfo("Asia/Tashkent")
        ).date() + dt.timedelta(days=2)
        made = await client.post(
            "/v1/admission/tasks",
            json={"title": "Send transcript", "deadline": soon.isoformat()},
        )
        assert made.status_code == 200, made.text
        after = (await client.get(TODAY)).json()
        assert after["streak"]["days"] == 1
        assert after["streak"]["today_done"] is True
        assert after["streak"]["last7"] == [False] * 6 + [True]
        top = after["next"][0]
        assert top["title"] == "Send transcript"
        assert "2" in top["why"]


async def test_own_essay_counts_toward_the_streak(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
) -> None:
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "todayessay"
    )
    async with client:
        assert (await client.get(TODAY)).json()["streak"]["today_done"] is False
        made = await client.post("/v1/admission/essays", json={"title": "Me"})
        assert made.status_code in (200, 201), made.text
        feed = (await client.get(TODAY)).json()
        assert feed["streak"]["today_done"] is True
        assert feed["streak"]["days"] == 1

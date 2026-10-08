"""ID-7: the internal EMIS gateway API: service token, JSON shapes, error mapping."""

from types import SimpleNamespace
from uuid import UUID

from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.interfaces.http.internal.emis import ROUTERS
from app.modules.identity.application.register_models import EmisNotConfiguredError
from app.settings import Settings
from tests.conftest import HttpClientFactory
from tests.identity.emis.world import World

import pytest
from httpx import AsyncClient


@pytest.fixture
async def api(
    world: World, http_client: HttpClientFactory, settings: Settings
) -> tuple[AsyncClient, UUID, dict[str, str]]:
    """A client of the internal router plus a registered student and auth headers."""
    _, registered = await world.register()
    client = await http_client(
        ROUTERS, identity=SimpleNamespace(emis=SimpleNamespace(gateway=world.gateway))
    )
    token = settings.tokens.service_token.get_secret_value()
    return client, registered.user_id, {"Authorization": f"Bearer {token}"}


async def test_a_call_without_the_service_token_is_unauthorized(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ID-7: only internal callers may read EMIS data."""
    client, user_id, _ = api

    response = await client.get(f"/internal/emis/{user_id}/profile")

    assert response.status_code == 401
    assert response.json()["type"] == "auth/unauthorized"
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("header", ["Bearer wrong", "Basic abc", "dev-service-token"])
async def test_a_wrong_token_is_unauthorized(
    api: tuple[AsyncClient, UUID, dict[str, str]], header: str
) -> None:
    """ID-7: wrong tokens and wrong schemes are refused."""
    client, user_id, _ = api

    response = await client.get(
        f"/internal/emis/{user_id}/profile", headers={"Authorization": header}
    )

    assert response.status_code == 401


async def test_profile_is_returned_as_json(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ID-7: the EmisProfile contract as JSON."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/profile", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "emis_student_id": 78201,
        "first_name": "Alisher",
        "last_name": "Abdullayev",
        "middle_name": "Alisherovich",
        "institution_id": 10815,
        "group_emis_id": 3292,
        "group_name": "2TN2",
        "current_semester": 3,
        "curriculum_id": 2124,
    }


async def test_subjects_are_returned_as_a_list(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """SYNC-3: EmisSubject[]."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/subjects", headers=headers)

    body = response.json()
    assert len(body) == 8
    assert body[0] == {
        "emis_subject_id": 101,
        "name_uz": "Matematika",
        "name_ru": "Математика",
        "name_en": "Mathematics",
    }


async def test_ratings_take_subject_and_semester(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """SYNC-2: EmisSubjectRatings with ISO dates and the hash."""
    client, user_id, headers = api

    response = await client.get(
        f"/internal/emis/{user_id}/ratings?subject=101&semester=3", headers=headers
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["emis_subject_id"], body["semester"]) == (101, 3)
    assert body["marks"][0].keys() == {"type", "date", "value"}
    assert body["marks"][0]["type"] == "lesson"
    assert len(body["payload_hash"]) == 64


async def test_class_hours_are_returned_as_a_list(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ACA-4: EmisClassHour[] with 0-based pairs."""
    client, user_id, headers = api

    response = await client.get(
        f"/internal/emis/{user_id}/class-hours", headers=headers
    )

    body = response.json()
    assert response.status_code == 200
    assert [p["pair_number"] for p in body] == [0, 1, 2, 3, 4]
    assert body[0] == {
        "pair_number": 0,
        "begin_time": "08:30:00",
        "end_time": "09:50:00",
    }


async def test_the_timetable_is_returned_with_teachers_halves_and_parity(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ACA-1: EmisTimetableItem[] of the student's group."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/timetable", headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert body[0].keys() == {
        "weekday",
        "pair_number",
        "subject_emis_id",
        "subject_name",
        "teacher",
        "room",
        "subgroup",
        "week_parity",
    }
    assert body[0]["teacher"].keys() == {
        "emis_id",
        "first_name",
        "last_name",
        "middle_name",
    }
    assert {item["subgroup"] for item in body} == {None, 1, 2}


async def test_the_timetable_needs_the_service_token(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ID-7: the new routes are as private as the old ones."""
    client, user_id, _ = api

    for path in ("timetable", "class-hours"):
        response = await client.get(f"/internal/emis/{user_id}/{path}")
        assert response.status_code == 401


async def test_an_unconfigured_timetable_endpoint_is_a_503_problem(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """ACA-1: until the endpoint is known, the worker sees "EMIS unavailable"."""
    client, user_id, headers = api
    world.emis.timetable_error = EmisNotConfiguredError("not configured")

    response = await client.get(f"/internal/emis/{user_id}/timetable", headers=headers)

    assert response.status_code == 503
    assert response.json()["type"] == "emis/unavailable"


async def test_missing_query_parameters_are_a_validation_error(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """SYNC-2: subject and semester are required."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/ratings", headers=headers)

    assert response.status_code == 422
    assert response.json()["type"] == "common/request-validation"


async def test_a_link_that_needs_reauth_is_a_401_emis_problem(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """SYNC-8: HttpEmisSource turns this back into EmisAuthFailed."""
    client, user_id, headers = api
    world.repo.accounts[user_id].emis_status = "needs_reauth"

    response = await client.get(f"/internal/emis/{user_id}/profile", headers=headers)

    assert response.status_code == 401
    assert response.json()["type"] == "emis/auth-failed"


async def test_an_emis_outage_is_a_503_problem(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """SYNC-8: retry next run."""
    client, user_id, headers = api
    world.emis.down = True

    response = await client.get(f"/internal/emis/{user_id}/profile", headers=headers)

    assert response.status_code == 503
    assert response.json()["type"] == "emis/unavailable"


async def test_http_source_and_router_work_together(
    world: World,
    api: tuple[AsyncClient, UUID, dict[str, str]],
    settings: Settings,
) -> None:
    """ID-7: what the gateway returns is what HttpEmisSource hands to the worker."""
    client, user_id, _ = api
    source = HttpEmisSource(
        gateway_url="http://test/internal/emis",
        service_token=settings.tokens.service_token.get_secret_value(),
        http=client,
    )

    direct_profile = await world.gateway.profile(user_id)
    direct_ratings = await world.gateway.ratings(user_id, 101, 3)

    assert await source.profile(user_id) == direct_profile
    assert await source.ratings(user_id, 101, 3) == direct_ratings
    assert await source.subjects(user_id) == await world.gateway.subjects(user_id)
    assert await source.class_hours(user_id) == await world.gateway.class_hours(user_id)
    assert await source.timetable(user_id) == await world.gateway.timetable(user_id)

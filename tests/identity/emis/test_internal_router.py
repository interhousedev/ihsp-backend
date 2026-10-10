"""ID-7: the internal EMIS gateway API: service token, JSON shapes, error mapping."""

from datetime import date
from types import SimpleNamespace
from uuid import UUID

from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.interfaces.http.internal.emis import ROUTERS
from app.modules.identity.application.register_models import EmisRequestError
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


async def test_the_curriculum_is_returned_as_json_with_iso_dates(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """SYNC-3: EmisCurriculum as snake_case JSON, dates as YYYY-MM-DD."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/curriculum", headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert body.keys() == {
        "emis_id",
        "name",
        "direction",
        "speciality",
        "edu_form",
        "language_code",
        "rating_min",
        "rating_max",
        "start_year",
        "end_year",
        "semesters_count",
        "status",
        "semesters",
        "subjects",
        "semester_subjects",
        "exams",
        "vocational_subjects",
    }
    assert (body["emis_id"], body["name"]) == (2124, "ТН, МТН, БТН 2025-2027")
    assert body["direction"] == {
        "emis_id": 312,
        "name": "Umumiy o'rta ta'lim",
        "code": "3010100",
    }
    assert body["speciality"] == {
        "uz": "Texnologik yo'nalish",
        "ru": "Технологическое направление",
        "en": "Technology track",
    }
    assert (body["edu_form"], body["language_code"], body["status"]) == (
        "Kunduzgi",
        "RU",
        "APPROVED",
    )
    assert (body["rating_min"], body["rating_max"], body["semesters_count"]) == (
        3,
        5,
        4,
    )
    assert body["start_year"] == {
        "code": "2025",
        "name": "2025-2026",
        "from_date": "2025-09-01",
        "to_date": "2026-08-31",
    }
    assert body["end_year"]["from_date"] == "2026-09-01"
    assert body["semesters"][0] == {
        "number": 1,
        "starts_on": "2025-09-03",
        "ends_on": "2026-01-20",
    }
    assert len(body["semesters"]) == 4


async def test_the_curriculum_lists_subjects_exams_and_semester_hours(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """SYNC-3: nested names are {uz, ru, en}; the hours sit on every line."""
    client, user_id, headers = api

    response = await client.get(f"/internal/emis/{user_id}/curriculum", headers=headers)

    body = response.json()
    assert body["subjects"][0] == {
        "emis_subject_id": 101,
        "name": {"uz": "Matematika", "ru": "Математика", "en": "Mathematics"},
        "subject_type_id": 2,
        "study_hours": 340,
    }
    assert body["subjects"][4]["name"] == {"uz": "O'zbek tili", "ru": "", "en": ""}
    assert len(body["semester_subjects"]) == 32
    assert body["semester_subjects"][2] == {
        "semester_number": 1,
        "emis_subject_id": 103,
        "name": {"uz": "Ingliz tili", "ru": "Английский язык", "en": "English"},
        "subject_type_id": 1,
        "study_hours": 51,
        "class_hours": 34,
        "independent_hours": 17,
        "is_separated": True,
    }
    assert body["semester_subjects"][3]["independent_hours"] is None
    assert body["exams"][1] == {
        "emis_id": 2,
        "name": {"uz": "Oraliq imtihon", "ru": "Промежуточный экзамен", "en": ""},
        "study_hours": 16,
    }
    assert [v["emis_id"] for v in body["vocational_subjects"]] == [7001, 7002]


async def test_the_curriculum_needs_the_service_token_and_a_valid_link(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """ID-7, SYNC-8: as private as the other routes; reauth is a 401 problem."""
    client, user_id, headers = api

    anonymous = await client.get(f"/internal/emis/{user_id}/curriculum")
    world.repo.accounts[user_id].emis_status = "needs_reauth"
    blocked = await client.get(f"/internal/emis/{user_id}/curriculum", headers=headers)

    assert anonymous.status_code == 401
    assert blocked.status_code == 401
    assert blocked.json()["type"] == "emis/auth-failed"


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


async def test_the_timetable_is_returned_class_by_class(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ACA-1: EmisClass[] of the student for begin..end, ISO dates."""
    client, user_id, headers = api

    response = await client.get(
        f"/internal/emis/{user_id}/timetable",
        params={"begin": "2026-10-05", "end": "2026-10-11"},
        headers=headers,
    )

    body = response.json()
    assert response.status_code == 200
    assert body[0].keys() == {
        "class_id",
        "date",
        "pair_number",
        "subject",
        "teacher",
        "room",
        "subgroup",
        "kind",
        "topic",
    }
    assert body[0]["subject"].keys() == {
        "emis_subject_id",
        "name_uz",
        "name_ru",
        "name_en",
    }
    assert body[0]["teacher"].keys() == {
        "emis_id",
        "first_name",
        "last_name",
        "middle_name",
    }
    assert {item["date"] for item in body} <= {f"2026-10-{d:02d}" for d in range(5, 12)}
    assert {item["subgroup"] for item in body} == {None, 1}
    assert {item["kind"] for item in body} <= {"lecture", "practice"}
    topics = [item["topic"] for item in body if item["topic"]]
    assert topics and topics[0].keys() == {
        "name",
        "description",
        "topic_file_url",
        "homework_file_url",
        "video_url",
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"begin": "2026-10-05"},
        {"begin": "2026-10-11", "end": "2026-10-05"},
        {"begin": "2026-10-01", "end": "2026-12-31"},
    ],
)
async def test_the_timetable_needs_a_sensible_date_range(
    api: tuple[AsyncClient, UUID, dict[str, str]], params: dict[str, str]
) -> None:
    """ACA-1: both dates are required and the range is at most two months."""
    client, user_id, headers = api

    response = await client.get(
        f"/internal/emis/{user_id}/timetable", params=params, headers=headers
    )

    assert response.status_code == 422


async def test_the_timetable_needs_the_service_token(
    api: tuple[AsyncClient, UUID, dict[str, str]],
) -> None:
    """ID-7: the new routes are as private as the old ones."""
    client, user_id, _ = api

    for path in ("timetable", "class-hours"):
        response = await client.get(f"/internal/emis/{user_id}/{path}")
        assert response.status_code == 401


async def test_an_unexpected_timetable_is_a_503_problem(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """ID-7: the worker sees "EMIS unavailable" when EMIS answers something odd."""
    client, user_id, headers = api
    world.emis.timetable_error = EmisRequestError("class schedules changed")

    response = await client.get(
        f"/internal/emis/{user_id}/timetable",
        params={"begin": "2026-10-05", "end": "2026-10-11"},
        headers=headers,
    )

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


async def test_a_student_without_a_stored_login_is_a_503_credentials_problem(
    world: World, api: tuple[AsyncClient, UUID, dict[str, str]]
) -> None:
    """The gateway reports the missing secret under its own type: the sync skips."""
    client, user_id, headers = api
    world.store.secrets.clear()

    response = await client.get(f"/internal/emis/{user_id}/profile", headers=headers)

    assert response.status_code == 503
    assert response.json()["type"] == "emis/credentials-missing"


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
    assert await source.curriculum(user_id) == await world.gateway.curriculum(user_id)
    assert await source.class_hours(user_id) == await world.gateway.class_hours(user_id)
    begin, end = date(2026, 10, 5), date(2026, 11, 1)
    assert await source.timetable(user_id, begin, end) == await world.gateway.timetable(
        user_id, begin, end
    )

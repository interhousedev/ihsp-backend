"""ID-7, SYNC (gateway side): HttpEmisSource calls the internal API with the token."""

from collections.abc import AsyncIterator, Iterator
from datetime import date, time
from uuid import UUID

from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisMarkType,
    EmisTeacher,
    EmisTopic,
    EmisUnavailable,
)

import httpx
import pytest
import respx

BASE = "http://identity.test/internal/emis"
USER = UUID(int=7)
PROFILE_JSON = {
    "emis_student_id": 78218,
    "first_name": "Aleksey",
    "last_name": "Brastilov",
    "middle_name": None,
    "institution_id": 10815,
    "group_emis_id": 3292,
    "group_name": "2TN2",
    "current_semester": 3,
    "curriculum_id": 2124,
}


@pytest.fixture
def gateway() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def source(gateway: respx.MockRouter) -> AsyncIterator[HttpEmisSource]:
    instance = HttpEmisSource(gateway_url=BASE + "/", service_token="svc-token")
    yield instance
    await instance.aclose()


async def test_profile_is_parsed_and_the_service_token_is_sent(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ID-7: the worker authenticates with the shared service token."""
    route = gateway.get(f"/{USER}/profile").respond(200, json=PROFILE_JSON)

    profile = await source.profile(USER)

    assert profile.emis_student_id == 78218
    assert (profile.group_name, profile.current_semester) == ("2TN2", 3)
    assert profile.middle_name is None
    assert route.calls.last.request.headers["Authorization"] == "Bearer svc-token"


async def test_subjects_are_parsed(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """SYNC-3: the curriculum comes back as EmisSubject objects."""
    gateway.get(f"/{USER}/subjects").respond(
        200,
        json=[
            {
                "emis_subject_id": 35,
                "name_uz": "Geometriya",
                "name_ru": "Геометрия",
                "name_en": "Geometry",
            }
        ],
    )

    subjects = await source.subjects(USER)

    assert [(s.emis_subject_id, s.name_en) for s in subjects] == [(35, "Geometry")]


async def test_ratings_send_subject_and_semester_and_parse_marks(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """SYNC-2: one request per subject and semester."""
    route = gateway.get(f"/{USER}/ratings").respond(
        200,
        json={
            "emis_subject_id": 35,
            "semester": 3,
            "semester_rating": 4,
            "marks": [{"type": "midterm", "date": "2026-10-20", "value": 4}],
            "payload_hash": "ab" * 32,
        },
    )

    ratings = await source.ratings(USER, 35, 3)

    assert dict(route.calls.last.request.url.params) == {
        "subject": "35",
        "semester": "3",
    }
    assert ratings.semester_rating == 4
    assert [(m.type, m.date, m.value) for m in ratings.marks] == [
        (EmisMarkType.MIDTERM, date(2026, 10, 20), 4)
    ]
    assert ratings.payload_hash == "ab" * 32


async def test_a_401_with_the_emis_problem_type_is_auth_failed(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """SYNC-8: the student must update the EMIS password."""
    gateway.get(f"/{USER}/profile").respond(
        401, json={"type": "emis/auth-failed", "status": 401}
    )

    with pytest.raises(EmisAuthFailed):
        await source.profile(USER)


async def test_a_503_is_unavailable(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """SYNC-8: EMIS down, retry next run."""
    gateway.get(f"/{USER}/profile").respond(
        503, json={"type": "emis/unavailable", "status": 503}
    )

    with pytest.raises(EmisUnavailable):
        await source.profile(USER)


async def test_a_rejected_service_token_is_our_problem_not_the_students(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ID-7: 401 auth/unauthorized must not mark students as needs_reauth."""
    gateway.get(f"/{USER}/profile").respond(
        401, json={"type": "auth/unauthorized", "status": 401}
    )

    with pytest.raises(EmisUnavailable) as caught:
        await source.profile(USER)

    assert "gateway answered 401" in caught.value.support_details


async def test_an_unreachable_gateway_is_unavailable(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ID-7: connection errors never look like authentication failures."""
    gateway.get(f"/{USER}/profile").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(EmisUnavailable):
        await source.profile(USER)


async def test_a_non_json_error_page_is_unavailable(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ID-7: a proxy error page is an outage."""
    gateway.get(f"/{USER}/profile").respond(502, text="<html>bad gateway</html>")

    with pytest.raises(EmisUnavailable):
        await source.profile(USER)


async def test_class_hours_are_parsed_from_the_gateway(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ACA-4: the worker gets the bells through the identity process."""
    route = gateway.get(f"/{USER}/class-hours").respond(
        200,
        json=[
            {"pair_number": 0, "begin_time": "08:30:00", "end_time": "09:50:00"},
            {"pair_number": 1, "begin_time": "10:10", "end_time": "11:30"},
        ],
    )

    hours = await source.class_hours(USER)

    assert [(h.pair_number, h.begin_time, h.end_time) for h in hours] == [
        (0, time(8, 30), time(9, 50)),
        (1, time(10, 10), time(11, 30)),
    ]
    assert route.calls.last.request.headers["Authorization"] == "Bearer svc-token"


async def test_the_timetable_is_parsed_from_the_gateway(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ACA-1: the dates go as ISO query parameters; teacher, half and topic survive."""
    route = gateway.get(f"/{USER}/timetable").respond(
        200,
        json=[
            {
                "class_id": 11,
                "date": "2026-10-05",
                "pair_number": 0,
                "subject": {
                    "emis_subject_id": 34,
                    "name_uz": "Algebra",
                    "name_ru": "Algebra",
                    "name_en": "Algebra",
                },
                "teacher": {
                    "emis_id": 2976,
                    "first_name": "Aleksandr",
                    "last_name": "Dryaxlov",
                    "middle_name": None,
                },
                "room": "23",
                "subgroup": 1,
                "kind": "practice",
                "topic": None,
            },
            {
                "class_id": 12,
                "date": "2026-10-05",
                "pair_number": 3,
                "subject": {
                    "emis_subject_id": 28,
                    "name_uz": "Tarix",
                    "name_ru": "История",
                    "name_en": "History",
                },
                "teacher": None,
                "room": None,
                "subgroup": None,
                "kind": "midterm",
                "topic": {
                    "name": "Jadids",
                    "description": None,
                    "topic_file_url": "https://cdn-emis.edu.uz/a.pdf",
                    "homework_file_url": None,
                    "video_url": None,
                },
            },
        ],
    )

    classes = await source.timetable(USER, date(2026, 10, 5), date(2026, 11, 1))

    assert dict(route.calls.last.request.url.params) == {
        "begin": "2026-10-05",
        "end": "2026-11-01",
    }
    first, second = classes
    assert (first.class_id, first.date, first.kind, first.subgroup) == (
        11,
        date(2026, 10, 5),
        "practice",
        1,
    )
    assert first.teacher == EmisTeacher(2976, "Aleksandr", "Dryaxlov", None)
    assert (first.subject.emis_subject_id, first.room, first.topic) == (34, "23", None)
    assert second.teacher is None and second.kind == "midterm"
    assert second.topic == EmisTopic(
        name="Jadids", topic_file_url="https://cdn-emis.edu.uz/a.pdf"
    )


async def test_a_timetable_503_is_unavailable(
    source: HttpEmisSource, gateway: respx.MockRouter
) -> None:
    """ACA-1: an unconfigured or failing EMIS timetable is "EMIS unavailable"."""
    gateway.get(f"/{USER}/timetable").respond(
        503, json={"type": "emis/unavailable", "status": 503}
    )

    with pytest.raises(EmisUnavailable):
        await source.timetable(USER, date(2026, 10, 5), date(2026, 10, 11))

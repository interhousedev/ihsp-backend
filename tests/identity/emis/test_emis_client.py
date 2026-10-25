"""ID-1, ID-7, SYNC-2: the EMIS client parses recorded responses and maps errors."""

import datetime as dt
from collections.abc import AsyncIterator, Iterator
from datetime import date, time

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.client import EmisClient
from app.modules.identity.infrastructure.emis.fake import (
    FakeEmisClient,
    fake_curriculum_result,
)
from app.modules.identity.infrastructure.emis.rate_limit import EmisRateLimiter
from app.shared.contracts.emis import EmisMarkType, EmisTeacher, EmisTopic
from app.shared.emis_pause import EmisPause
from tests.fakes.clock import FixedClock
from tests.identity.emis.emis_fixtures import load_fixture

import httpx
import pytest
import respx
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

BASE = "https://emis.test/api/v1/"
PROFILE = "student-profiles/profile/"
CURRICULUM = "student-profiles/curriculum/"
RATINGS = "student-profiles/edu-subjects/35/ratings/?semester=3"
CLASS_HOURS = "student-profiles/class-hours/"
CLASS_SCHEDULES = "student-profiles/class-schedules/"
WEEK_BEGINS = ["05.10.2026", "12.10.2026", "19.10.2026", "26.10.2026"]
WEEK_ENDS = ["11.10.2026", "18.10.2026", "25.10.2026", "01.11.2026"]


@pytest.fixture
def emis_http() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client(emis_http: respx.MockRouter) -> AsyncIterator[EmisClient]:
    http = httpx.AsyncClient(base_url=BASE)
    redis = FakeRedis(server=FakeServer(), decode_responses=True)
    yield EmisClient(
        http,
        profile_path=PROFILE,
        limiter=EmisRateLimiter(redis),
        pause=EmisPause(redis),
        max_qps=1000,
        file_max_qps=1000,
    )
    await http.aclose()


async def test_login_returns_the_access_token(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-1: login posts the credentials and returns result.access_token."""
    route = emis_http.post("student-profiles/login/").respond(
        200, json=load_fixture("login_200.json")
    )

    token = await client.login("student01", "password")

    assert token == "emis-token-1"
    assert route.calls.last.request.content == (
        b'{"login":"student01","password":"password"}'
    )


async def test_login_with_wrong_credentials_raises_auth_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-1: EMIS answers 401 for wrong credentials."""
    emis_http.post("student-profiles/login/").respond(
        401, json=load_fixture("login_401.json")
    )

    with pytest.raises(EmisAuthError):
        await client.login("student01", "wrong")


async def test_profile_maps_names_group_and_ids(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-1, ID-2: names become title case, the group name Latin upper case."""
    route = emis_http.get(PROFILE).respond(200, json=load_fixture("profile.json"))

    profile = await client.profile("emis-token-1")

    assert (profile.emis_student_id, profile.institution_id) == (78218, 10815)
    assert (profile.first_name, profile.last_name) == ("Aleksey", "Brastilov")
    assert profile.middle_name == "Mixaylovich"
    assert profile.group_name == "2TN2"
    assert (profile.group_emis_id, profile.curriculum_id) == (3292, 2124)
    assert profile.current_semester == 3
    assert route.calls.last.request.headers["Authorization"] == "emis-token-1"


async def test_curriculum_fills_an_empty_name_from_another_language(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-3: subjects keep their EMIS ids; empty names fall back (uz, ru, en)."""
    emis_http.get(CURRICULUM).respond(200, json=load_fixture("curriculum.json"))

    subjects = await client.curriculum("emis-token-1")

    assert [s.emis_subject_id for s in subjects] == [35, 19]
    assert (subjects[0].name_uz, subjects[0].name_ru, subjects[0].name_en) == (
        "Geometriya",
        "Geometriya",
        "Geometry",
    )
    assert subjects[1].name_ru == "Английский язык"


def _curriculum_body() -> dict[str, object]:
    return {
        "result": fake_curriculum_result(),
        "code": 200,
        "success": True,
        "error": None,
    }


async def test_curriculum_detail_maps_the_whole_curriculum(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-3: one request returns semesters, hours per semester, exams and scale."""
    route = emis_http.get(CURRICULUM).respond(200, json=_curriculum_body())

    curriculum = await client.curriculum_detail("emis-token-1")

    assert (curriculum.emis_id, curriculum.name) == (2124, "ТН, МТН, БТН 2025-2027")
    assert route.calls.last.request.headers["Authorization"] == "emis-token-1"
    assert [s.number for s in curriculum.semesters] == [1, 2, 3, 4]
    assert curriculum.semesters[0].starts_on == date(2025, 9, 3)
    assert len(curriculum.subjects) == 8
    assert len(curriculum.semester_subjects) == 32
    assert (curriculum.rating_min, curriculum.rating_max) == (3, 5)
    assert curriculum.language_code == "RU"
    assert len(curriculum.exams) == 3 and len(curriculum.vocational_subjects) == 2


async def test_curriculum_and_curriculum_detail_describe_the_same_subjects(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-3: curriculum() still returns the subjects list, with name fallback."""
    emis_http.get(CURRICULUM).respond(200, json=_curriculum_body())

    subjects = await client.curriculum("emis-token-1")
    detail = await client.curriculum_detail("emis-token-1")

    assert [s.emis_subject_id for s in subjects] == [
        s.emis_subject_id for s in detail.subjects
    ]
    uzbek = next(s for s in subjects if s.emis_subject_id == 105)
    assert (uzbek.name_uz, uzbek.name_ru, uzbek.name_en) == ("O'zbek tili",) * 3


async def test_curriculum_detail_reads_the_small_recorded_response(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-3: a response with only ids and names is a valid, bare curriculum."""
    emis_http.get(CURRICULUM).respond(200, json=load_fixture("curriculum.json"))

    curriculum = await client.curriculum_detail("emis-token-1")

    assert curriculum.emis_id == 2124
    assert [s.emis_subject_id for s in curriculum.subjects] == [35, 19]
    assert curriculum.semesters == () and curriculum.semester_subjects == ()
    assert curriculum.rating_min is None and curriculum.direction is None


async def test_curriculum_detail_with_a_changed_shape_raises_request_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-3: a curriculum without an id means EMIS changed."""
    emis_http.get(CURRICULUM).respond(
        200, json={"result": {"edu_subject": []}, "code": 200, "success": True}
    )

    with pytest.raises(EmisRequestError):
        await client.curriculum_detail("emis-token-1")


async def test_curriculum_detail_401_raises_auth_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a stale token is an auth error so the gateway can log in again."""
    emis_http.get(CURRICULUM).respond(401, json=load_fixture("login_401.json"))

    with pytest.raises(EmisAuthError):
        await client.curriculum_detail("old-token")


async def test_ratings_parse_all_three_mark_types(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-2, SYNC-5: Joriy, Oraliq and Yakuniy become lesson, midterm, final."""
    emis_http.get(RATINGS).respond(200, json=load_fixture("ratings_all_types.json"))

    ratings = await client.ratings("emis-token-1", 35, 3)

    assert (ratings.emis_subject_id, ratings.semester) == (35, 3)
    assert ratings.semester_rating == 4
    assert [(m.type, m.date, m.value) for m in ratings.marks] == [
        (EmisMarkType.LESSON, date(2026, 9, 4), 5),
        (EmisMarkType.LESSON, date(2026, 9, 4), 4),
        (EmisMarkType.LESSON, date(2026, 9, 11), 3),
        (EmisMarkType.MIDTERM, date(2026, 10, 20), 4),
        (EmisMarkType.FINAL, date(2026, 12, 25), 5),
    ]


async def test_ratings_without_marks_have_no_marks_and_no_rating(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-2: an empty ratings list and a null semester rating are valid."""
    emis_http.get(RATINGS).respond(200, json=load_fixture("ratings_empty.json"))

    ratings = await client.ratings("emis-token-1", 35, 3)

    assert ratings.marks == ()
    assert ratings.semester_rating is None


async def test_unknown_rating_groups_are_skipped(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-5: only the three known mark types are imported."""
    emis_http.get(RATINGS).respond(
        200, json=load_fixture("ratings_no_semester_rating.json")
    )

    ratings = await client.ratings("emis-token-1", 35, 3)

    assert [m.value for m in ratings.marks] == [5]
    assert ratings.semester_rating is None


async def test_payload_hash_is_stable_and_changes_with_the_data(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """SYNC-6: the hash ignores key order and differs for different results."""
    original = load_fixture("ratings_all_types.json")
    reordered = {"success": True, "result": dict(reversed(original["result"].items()))}
    route = emis_http.get(RATINGS)

    route.respond(200, json=original)
    first = (await client.ratings("t", 35, 3)).payload_hash
    route.respond(200, json=reordered)
    second = (await client.ratings("t", 35, 3)).payload_hash
    route.respond(200, json=load_fixture("ratings_empty.json"))
    third = (await client.ratings("t", 35, 3)).payload_hash

    assert first == second
    assert first != third
    assert len(first) == 64


async def test_class_hours_are_the_pairs_of_the_results_list(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ACA-4: the response has `results` (not `result`); pair numbers are 0-based."""
    route = emis_http.get(CLASS_HOURS).respond(
        200, json=load_fixture("class_hours.json")
    )

    hours = await client.class_hours("emis-token-1")

    assert [(h.pair_number, h.begin_time, h.end_time) for h in hours] == [
        (0, time(8, 30), time(9, 50)),
        (1, time(10, 10), time(11, 30)),
        (2, time(12, 10), time(13, 30)),
        (3, time(13, 40), time(15, 0)),
        (4, time(15, 10), time(16, 30)),
    ]
    assert route.calls.last.request.headers["Authorization"] == "emis-token-1"


@pytest.mark.parametrize(
    "body",
    [
        {"results": [{"pair_number": 0, "begin_time": "9am", "end_time": "09:50"}]},
        {"results": [{"pair_number": 0, "begin_time": "09:50", "end_time": "08:30"}]},
        {"results": [{"pair_number": -1, "begin_time": "08:30", "end_time": "09:50"}]},
        {"results": [{"begin_time": "08:30", "end_time": "09:50"}]},
        {"result": {"pairs": []}},
        [],
    ],
)
async def test_unexpected_class_hours_raise_request_error(
    client: EmisClient, emis_http: respx.MockRouter, body: object
) -> None:
    """ID-7: a changed shape is reported, never turned into bad bells."""
    emis_http.get(CLASS_HOURS).respond(200, json=body)

    with pytest.raises(EmisRequestError):
        await client.class_hours("t")


def week_route(
    router: respx.MockRouter, begin: str, end: str, body: object
) -> respx.Route:
    """Answer one `class-schedules` request for the week begin..end."""
    return router.get(
        CLASS_SCHEDULES, params={"begin_date": begin, "end_date": end}
    ).respond(200, json=body)


async def test_the_recorded_class_schedules_response_is_mapped_class_by_class(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ACA-1: DD.MM.YYYY dates, a null `classes` day is empty, halves and kinds map."""
    route = week_route(
        emis_http,
        "05.10.2026",
        "11.10.2026",
        load_fixture("class_schedules_sample.json"),
    )

    classes = await client.timetable(
        "emis-token-1", dt.date(2026, 10, 5), dt.date(2026, 10, 11)
    )

    assert route.calls.last.request.headers["Authorization"] == "emis-token-1"
    assert [(c.class_id, c.date, c.pair_number) for c in classes] == [
        (3185314, dt.date(2026, 10, 5), 0),
        (3185325, dt.date(2026, 10, 5), 3),
    ]
    split, midterm = classes
    assert (split.subject.emis_subject_id, split.subject.name_en) == (34, "Algebra")
    assert split.subject.name_ru == "Algebra"  # EMIS sent an empty Russian name
    assert (split.kind, split.subgroup, split.room, split.topic) == (
        "practice",
        1,
        "23",
        None,
    )
    assert split.teacher == EmisTeacher(2976, "Aleksandr", "Dryaxlov", "Viktorovich")
    assert (midterm.kind, midterm.subgroup, midterm.room) == ("midterm", None, "102")
    assert midterm.subject.name_ru == "История Узбекистана"
    assert midterm.topic == EmisTopic(
        name="Движение джадидов. Наука и культура в Туркестане. ПК-1",
        description="освоить тему",
        topic_file_url="https://cdn-emis.edu.uz/files/4a5c9ef7-0001.pdf",
        homework_file_url="https://cdn-emis.edu.uz/files/ceb51d0d-0002.pdf",
        video_url="https://www.youtube.com/watch?v=q0sUmfmG7gI",
    )


async def test_four_weeks_take_four_requests_and_match_the_fake(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ACA-1: one request per week; the fake EMIS answers with the same shape."""
    routes = [
        week_route(
            emis_http, begin, end, load_fixture(f"class_schedules_week{n + 1}.json")
        )
        for n, (begin, end) in enumerate(zip(WEEK_BEGINS, WEEK_ENDS, strict=True))
    ]

    classes = await client.timetable("t", dt.date(2026, 10, 5), dt.date(2026, 11, 1))

    assert [route.call_count for route in routes] == [1, 1, 1, 1]
    fake = FakeEmisClient(FixedClock())
    token = await fake.login("student01", "password")
    assert classes == await fake.timetable(
        token, dt.date(2026, 10, 5), dt.date(2026, 11, 1)
    )
    assert {c.kind for c in classes} == {"lecture", "practice", "midterm"}
    assert not [c for c in classes if c.date.isoweekday() == 6]  # no Saturday classes


async def test_a_range_is_split_at_mondays(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ACA-1: Wednesday to the next Tuesday is two requests."""
    empty = {"results": [], "total_pages": 1, "success": True}
    first = week_route(emis_http, "07.10.2026", "11.10.2026", empty)
    second = week_route(emis_http, "12.10.2026", "13.10.2026", empty)

    assert (
        await client.timetable("t", dt.date(2026, 10, 7), dt.date(2026, 10, 13)) == []
    )

    assert (first.call_count, second.call_count) == (1, 1)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Ma'ruza", "lecture"),
        ("Ma’ruza", "lecture"),
        ("MAʼRUZA", "lecture"),
        ("Amaliyot", "practice"),
        ("Oraliq nazorat", "midterm"),
        ("Yakuniy nazorat", "final"),
        ("Laboratoriya", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_class_type_names_map_to_lesson_kinds(name: str | None, kind: str) -> None:
    """ACA-7: apostrophes and case do not matter; unknown names are "other"."""
    from app.modules.identity.infrastructure.emis.mapping import class_kind

    assert class_kind(name) == kind


async def test_odd_shapes_of_a_class_are_handled(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ACA-1: no subject skips the class; plain classes have no half; bad URLs go."""
    teacher = {
        "edu_subject": {"id": 5, "name": {"uz": "", "ru": "", "en": ""}},
        "class_type": {"name": "Yakuniy nazorat"},
        "teacher": {"id": 1, "citizen": {"first_name": "", "last_name": ""}},
        "room": {"name": " "},
        "group_number": 2,
        "topic": {"name": "T", "topic_file_url": "ftp://x/y", "video_url": " "},
    }
    body = {
        "results": [
            {
                "date": "05.10.2026",
                "classes": [
                    {
                        "id": 1,
                        "is_seperated": False,
                        "pair_number": 1,
                        "teachers": [teacher],
                    },
                    {"id": 2, "pair_number": 2, "teachers": [{"room": {"name": "9"}}]},
                    {"id": 3, "pair_number": 3, "teachers": None},
                ],
            }
        ]
    }
    week_route(emis_http, "05.10.2026", "11.10.2026", body)

    classes = await client.timetable("t", dt.date(2026, 10, 5), dt.date(2026, 10, 11))

    [only] = classes
    assert (only.class_id, only.subgroup, only.kind) == (1, None, "final")
    assert only.subject.name_uz == "Subject 5"  # every name was empty
    assert (only.teacher, only.room) == (None, None)
    assert only.topic == EmisTopic(name="T")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"result": {}},
        {"results": [{"date": "5 Oct", "classes": None}]},
        {
            "results": [
                {"date": "05.10.2026", "classes": [{"id": 1, "pair_number": -1}]}
            ]
        },
        {"results": [{"date": "05.10.2026", "classes": [{"pair_number": 0}]}]},
    ],
)
async def test_unexpected_class_schedules_raise_request_error(
    client: EmisClient, emis_http: respx.MockRouter, body: object
) -> None:
    """ID-7: a changed shape is reported, never turned into wrong lessons."""
    week_route(emis_http, "05.10.2026", "11.10.2026", body)

    with pytest.raises(EmisRequestError):
        await client.timetable("t", dt.date(2026, 10, 5), dt.date(2026, 10, 11))


async def test_a_stale_token_on_class_schedules_is_an_auth_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a 401 on the timetable means the token is stale like on any endpoint."""
    emis_http.get(CLASS_SCHEDULES).respond(401, json={"code": 401})

    with pytest.raises(EmisAuthError):
        await client.timetable("stale", dt.date(2026, 10, 5), dt.date(2026, 10, 11))


@pytest.mark.parametrize(
    ("path", "call"),
    [
        (PROFILE, "profile"),
        (CURRICULUM, "curriculum"),
        (RATINGS, "ratings"),
        (CLASS_HOURS, "class_hours"),
    ],
)
async def test_401_on_a_data_endpoint_raises_auth_error(
    client: EmisClient, emis_http: respx.MockRouter, path: str, call: str
) -> None:
    """ID-7: any 401, not only the login one, means the token is stale."""
    emis_http.get(path).respond(401, json={"code": 401})

    with pytest.raises(EmisAuthError):
        if call == "ratings":
            await client.ratings("stale", 35, 3)
        else:
            await getattr(client, call)("stale")


async def test_server_error_raises_request_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a 5xx is an outage, not an authentication failure."""
    emis_http.get(PROFILE).respond(503)

    with pytest.raises(EmisRequestError):
        await client.profile("t")


async def test_invalid_json_raises_request_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a body that is not JSON is an unexpected response."""
    emis_http.get(PROFILE).respond(200, text="<html>maintenance</html>")

    with pytest.raises(EmisRequestError):
        await client.profile("t")


async def test_unexpected_shape_raises_request_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a profile without a group means EMIS changed its API."""
    broken = load_fixture("profile.json")
    del broken["result"]["edu_group"]
    emis_http.get(PROFILE).respond(200, json=broken)

    with pytest.raises(EmisRequestError):
        await client.profile("t")


async def test_network_error_raises_request_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """ID-7: a connection failure is an outage."""
    emis_http.get(PROFILE).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(EmisRequestError):
        await client.profile("t")


async def test_ratings_without_attendance_fields_report_none(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """The real ratings response has no attendance, so nothing is reported."""
    emis_http.get(RATINGS).respond(200, json=load_fixture("ratings_all_types.json"))

    ratings = await client.ratings("emis-token-1", 35, 3)

    assert (ratings.absent_dates, ratings.absence_total) == (None, None)


async def test_ratings_read_absence_flags_and_totals_when_present(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """An "nb" row without a mark is an absence; a subject total is kept."""
    body = {
        "result": {
            "ratings": [
                {
                    "name": "Joriy nazorat",
                    "dailyRatings": [
                        {"class_date": "04.09.2026", "rating": 5, "nb": False},
                        {"class_date": "11.09.2026", "rating": None, "nb": True},
                    ],
                }
            ],
            "semester_rating": 4,
            "absences_count": 3,
        },
        "code": 200,
        "success": True,
        "error": None,
    }
    emis_http.get(RATINGS).respond(200, json=body)

    ratings = await client.ratings("emis-token-1", 35, 3)

    assert [m.value for m in ratings.marks] == [5]
    assert ratings.absent_dates == (date(2026, 9, 11),)
    assert ratings.absence_total == 3

"""ID-1, ID-7, SYNC-2: the EMIS client parses recorded responses and maps errors."""

from collections.abc import AsyncIterator, Iterator
from datetime import date

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.client import EmisClient
from app.shared.contracts.emis import EmisMarkType
from tests.identity.emis.emis_fixtures import load_fixture

import httpx
import pytest
import respx

BASE = "https://emis.test/api/v1/"
PROFILE = "student-profiles/profile/"
CURRICULUM = "student-profiles/curriculum/"
RATINGS = "student-profiles/edu-subjects/35/ratings/?semester=3"


@pytest.fixture
def emis_http() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client(emis_http: respx.MockRouter) -> AsyncIterator[EmisClient]:
    http = httpx.AsyncClient(base_url=BASE)
    yield EmisClient(http, profile_path=PROFILE)
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


@pytest.mark.parametrize(
    ("path", "call"),
    [
        (PROFILE, "profile"),
        (CURRICULUM, "curriculum"),
        (RATINGS, "ratings"),
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

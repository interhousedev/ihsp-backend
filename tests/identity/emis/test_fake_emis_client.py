"""ID-1: the fake EMIS used in development (EMIS__MODE=fake)."""

from datetime import UTC, datetime

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.fake import (
    FAKE_CLASS_HOURS,
    FAKE_STUDENTS,
    FAKE_SUBJECTS,
    FakeEmisClient,
)
from app.modules.identity.infrastructure.emis.mapping import to_class_hours
from app.modules.identity.infrastructure.emis.models.responses.class_hours import (
    ClassHoursV1DTO,
)
from app.shared.contracts.emis import EmisMarkType
from tests.fakes.clock import FixedClock
from tests.identity.emis.emis_fixtures import load_fixture

import pytest


def make_client(now: datetime | None = None) -> FakeEmisClient:
    return FakeEmisClient(FixedClock(now))


async def test_there_are_thirty_students_with_unique_names_and_ids() -> None:
    """ID-1: student01 to student30, 15 per group."""
    logins = [s.login for s in FAKE_STUDENTS]

    assert logins[0] == "student01"
    assert logins[-1] == "student30"
    assert len({s.emis_student_id for s in FAKE_STUDENTS}) == 30
    assert len({(s.last_name, s.first_name) for s in FAKE_STUDENTS}) == 30
    assert len(FAKE_SUBJECTS) == 8


@pytest.mark.parametrize(
    ("login", "group", "semester", "group_id"),
    [("student01", "2TN2", 3, 3292), ("student16", "1TN1", 1, 3291)],
)
async def test_profile_matches_the_students_group(
    login: str, group: str, semester: int, group_id: int
) -> None:
    """ID-1, ID-2: the group is normalized, institution 10815."""
    client = make_client()
    token = await client.login(login, "password")

    profile = await client.profile(token)

    assert profile.group_name == group
    assert profile.current_semester == semester
    assert profile.group_emis_id == group_id
    assert profile.institution_id == 10815
    assert profile.first_name == profile.first_name.capitalize()


@pytest.mark.parametrize(
    ("login", "password"),
    [("student01", "wrong"), ("student31", "password"), ("badpass", "password")],
)
async def test_wrong_credentials_raise_auth_error(login: str, password: str) -> None:
    """ID-1: unknown logins and wrong passwords are rejected."""
    with pytest.raises(EmisAuthError):
        await make_client().login(login, password)


async def test_login_down_simulates_an_outage() -> None:
    """ID-7: the login ``down`` always fails like an EMIS outage."""
    with pytest.raises(EmisRequestError):
        await make_client().login("down", "password")


async def test_data_endpoints_reject_a_foreign_token() -> None:
    """ID-7: a token that was not issued by login is a 401."""
    with pytest.raises(EmisAuthError):
        await make_client().profile("garbage")


async def test_marks_are_deterministic_and_stop_at_today() -> None:
    """SYNC-2: same input, same marks; none after the fake today."""
    first = make_client()
    second = make_client()
    token = await first.login("student01", "password")

    one = await first.ratings(token, 101, 3)
    two = await second.ratings(await second.login("student01", "password"), 101, 3)

    assert one == two
    assert one.marks
    assert all(m.date <= datetime(2026, 10, 6, tzinfo=UTC).date() for m in one.marks)
    assert all(2 <= m.value <= 5 for m in one.marks)
    assert all(m.date.weekday() < 6 for m in one.marks)
    assert one.semester_rating is not None


async def test_midterm_appears_after_the_midterm_date() -> None:
    """SYNC-5: one midterm on 2026-10-20 once today has passed it."""
    before = make_client()
    after = make_client(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))

    early = await before.ratings(await before.login("student01", "password"), 101, 3)
    late = await after.ratings(await after.login("student01", "password"), 101, 3)

    assert not [m for m in early.marks if m.type is EmisMarkType.MIDTERM]
    assert len([m for m in late.marks if m.type is EmisMarkType.MIDTERM]) == 1
    assert early.payload_hash != late.payload_hash


async def test_future_semesters_have_no_marks_and_past_ones_do() -> None:
    """SYNC-4: backfill reads semesters 1-4; a second-year student has 1-3."""
    client = make_client()
    token = await client.login("student01", "password")

    semester_one = await client.ratings(token, 101, 1)
    semester_four = await client.ratings(token, 101, 4)

    assert semester_one.marks
    assert semester_four.marks == ()
    assert semester_four.semester_rating is None


async def test_class_hours_are_the_recorded_emis_response() -> None:
    """ACA-4: the fake answers exactly what the real class-hours endpoint did."""
    client = make_client()
    token = await client.login("student01", "password")

    hours = await client.class_hours(token)

    recorded = to_class_hours(
        ClassHoursV1DTO.model_validate(load_fixture("class_hours.json"))
    )
    assert hours == recorded == list(FAKE_CLASS_HOURS)


async def test_the_timetable_belongs_to_the_students_group() -> None:
    """ACA-1: two groups, different timetables, teachers shared by id."""
    client = make_client()
    second_year = await client.timetable(await client.login("student01", "password"))
    first_year = await client.timetable(await client.login("student16", "password"))

    assert second_year and first_year and second_year != first_year
    teachers = {i.teacher.emis_id for i in second_year if i.teacher} & {
        i.teacher.emis_id for i in first_year if i.teacher
    }
    assert teachers  # the same teachers teach both groups
    assert {i.subgroup for i in second_year} == {None, 1, 2}
    assert {i.week_parity for i in second_year} == {"every", "odd", "even"}
    assert all(1 <= i.weekday <= 6 and i.pair_number >= 0 for i in second_year)


async def test_the_timetable_needs_a_valid_token() -> None:
    """ID-7: the timetable is behind the student's token like every data call."""
    client = make_client()

    with pytest.raises(EmisAuthError):
        await client.timetable("fake-token:nobody")

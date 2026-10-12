"""ID-1: the fake EMIS used in development (EMIS__MODE=fake)."""

from datetime import UTC, date, datetime, timedelta

import app.modules.identity.infrastructure.emis.fake as fake_module
from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.fake import (
    FAKE_CLASS_HOURS,
    FAKE_CURRICULUM_PATH,
    FAKE_STUDENTS,
    FAKE_SUBJECTS,
    FakeEmisClient,
    FakeStudent,
    fake_curriculum_result,
)
from app.modules.identity.infrastructure.emis.fake_schedule import week_body
from app.modules.identity.infrastructure.emis.mapping import (
    to_class_hours,
    to_curriculum,
)
from app.modules.identity.infrastructure.emis.models.responses.class_hours import (
    ClassHoursV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)
from app.shared.contracts.emis import EmisClass, EmisMarkType
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
    assert all(m.date.weekday() < 5 for m in one.marks)
    assert one.semester_rating is not None


async def test_marks_follow_the_five_point_scale_mostly_fours_and_fives() -> None:
    """ACA-15: demo marks are 2 to 5 on the lyceum scale, mostly 4 and 5, 2 rare."""
    client = make_client()
    values: list[int] = []
    for student in FAKE_STUDENTS:
        token = await client.login(student.login, "password")
        for subject in FAKE_SUBJECTS:
            ratings = await client.ratings(token, subject.emis_subject_id, 1)
            values += [m.value for m in ratings.marks if m.type is EmisMarkType.LESSON]

    share = {mark: values.count(mark) / len(values) for mark in range(2, 6)}
    assert set(values) <= {2, 3, 4, 5}
    assert share[4] + share[5] > 0.6
    assert 0 < share[2] < 0.1
    assert share[5] > share[3] > share[2]


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


WINDOW = (date(2026, 10, 5), date(2026, 11, 1))  # four weeks from the fake's Monday


async def test_the_fake_week_bodies_are_the_recorded_fixtures() -> None:
    """ACA-1: the fixtures are what the fake sends; both have the real EMIS shape."""
    client = make_client()
    student = _student("student01")
    cells = fake_module._cells_of(student.group_emis_id)
    today = date(2026, 10, 6)

    for number in range(4):
        monday = WINDOW[0] + timedelta(days=7 * number)
        body = week_body(
            cells,
            student.group_emis_id,
            student.half,
            monday,
            monday + timedelta(days=6),
            today,
        )
        assert body == load_fixture(f"class_schedules_week{number + 1}.json")
    assert await client.timetable(await client.login("student01", "password"), *WINDOW)


async def test_the_timetable_belongs_to_the_students_group() -> None:
    """ACA-1: two groups, different timetables, teachers shared by id."""
    client = make_client()
    second_year = await client.timetable(
        await client.login("student01", "password"), *WINDOW
    )
    first_year = await client.timetable(
        await client.login("student16", "password"), *WINDOW
    )

    assert second_year and first_year

    def plan(classes: list[EmisClass]) -> set[tuple[date, int, int]]:
        return {(c.date, c.pair_number, c.subject.emis_subject_id) for c in classes}

    assert plan(second_year) != plan(first_year)
    teachers = {c.teacher.emis_id for c in second_year if c.teacher} & {
        c.teacher.emis_id for c in first_year if c.teacher
    }
    assert teachers  # the same teachers teach both groups
    assert all(
        1 <= c.date.isoweekday() <= 5 and c.pair_number >= 0 for c in second_year
    )
    assert len({c.class_id for c in second_year}) == len(second_year)


async def test_a_student_sees_only_the_slots_of_their_own_half() -> None:
    """ACA-2: halves 1 and 2 of one group see the same whole-group classes."""
    client = make_client()
    one = await client.timetable(await client.login("student01", "password"), *WINDOW)
    two = await client.timetable(await client.login("student02", "password"), *WINDOW)

    assert {c.subgroup for c in one} == {None, 1}
    assert {c.subgroup for c in two} == {None, 2}

    def whole(classes: list[EmisClass]) -> set[tuple[date, int, int]]:
        return {
            (c.date, c.pair_number, c.class_id) for c in classes if c.subgroup is None
        }

    assert whole(one) == whole(two)
    assert {(c.date, c.pair_number) for c in one} == {
        (c.date, c.pair_number) for c in two
    }


async def test_the_fake_makes_no_saturday_classes() -> None:
    """ACA-5: the lyceum does not study on Saturday; classes are Monday to Friday."""
    client = make_client()
    for login in ("student01", "student16"):
        classes = await client.timetable(await client.login(login, "password"), *WINDOW)

        assert classes
        assert not [c for c in classes if c.date.isoweekday() == 6]
        assert {c.date.isoweekday() for c in classes} == {1, 2, 3, 4, 5}


async def test_kinds_and_topics_follow_the_calendar() -> None:
    """ACA-7: a midterm on 20 Oct; topics exist for days up to the fake's today only."""
    client = make_client()
    classes = await client.timetable(
        await client.login("student01", "password"), *WINDOW
    )

    midterms = [c for c in classes if c.kind == "midterm"]
    assert {(c.date, c.pair_number) for c in midterms} == {(date(2026, 10, 20), 0)}
    assert {c.kind for c in classes} == {"lecture", "practice", "midterm"}
    with_topic = [c for c in classes if c.topic is not None]
    assert with_topic and all(c.date <= date(2026, 10, 6) for c in with_topic)
    assert any(c.topic and c.topic.topic_file_url for c in with_topic)


async def test_the_timetable_needs_a_valid_token() -> None:
    """ID-7: the timetable is behind the student's token like every data call."""
    client = make_client()

    with pytest.raises(EmisAuthError):
        await client.timetable("fake-token:nobody", *WINDOW)


def _student(login: str) -> FakeStudent:
    return next(s for s in FAKE_STUDENTS if s.login == login)


async def test_the_fake_curriculum_is_the_sample_file_through_the_real_mapping() -> (
    None
):
    """SYNC-3: curriculum_detail parses fake_data/curriculum.json like the client."""
    client = make_client()
    token = await client.login("student01", "password")

    curriculum = await client.curriculum_detail(token)

    assert FAKE_CURRICULUM_PATH.name == "curriculum.json"
    assert curriculum == to_curriculum(
        CurriculumV1DTO.model_validate(fake_curriculum_result())
    )
    assert curriculum.name == "ТН, МТН, БТН 2025-2027"
    assert [s.number for s in curriculum.semesters] == [1, 2, 3, 4]
    assert (curriculum.semesters[0].starts_on, curriculum.semesters[0].ends_on) == (
        date(2025, 9, 3),
        date(2026, 1, 20),
    )
    assert (curriculum.rating_min, curriculum.rating_max) == (3, 5)
    assert curriculum.language_code == "RU" and curriculum.status == "APPROVED"
    assert curriculum.exams and curriculum.vocational_subjects
    assert {s.subject_type_id for s in curriculum.subjects} == {1, 2, 3, 4}
    assert any(s.name.ru == "" and s.name.en == "" for s in curriculum.subjects)


async def test_the_fake_curriculum_has_the_subjects_of_the_fake_timetable() -> None:
    """ACA-1: same EMIS ids, and the same names wherever the sample names them."""
    client = make_client()
    detail = await client.curriculum_detail(await client.login("student01", "password"))

    assert [s.emis_subject_id for s in detail.subjects] == [
        s.emis_subject_id for s in FAKE_SUBJECTS
    ]
    for semester in (1, 2, 3, 4):
        in_semester = [
            s.emis_subject_id
            for s in detail.semester_subjects
            if s.semester_number == semester
        ]
        assert in_semester == [s.emis_subject_id for s in FAKE_SUBJECTS]
    fake = {s.emis_subject_id: s for s in FAKE_SUBJECTS}
    for item in detail.subjects:
        assert item.name.uz == fake[item.emis_subject_id].name_uz
        assert item.name.ru in ("", fake[item.emis_subject_id].name_ru)
        assert item.name.en in ("", fake[item.emis_subject_id].name_en)


async def test_curriculum_returns_the_subjects_list_of_the_same_curriculum() -> None:
    """SYNC-3: curriculum(token) is the subject view with the name fallback."""
    client = make_client()
    token = await client.login("student01", "password")

    subjects = await client.curriculum(token)
    detail = await client.curriculum_detail(token)

    assert [s.emis_subject_id for s in subjects] == [
        s.emis_subject_id for s in detail.subjects
    ]
    assert (subjects[0].name_uz, subjects[0].name_ru, subjects[0].name_en) == (
        "Matematika",
        "Математика",
        "Mathematics",
    )
    uzbek = next(s for s in subjects if s.emis_subject_id == 105)
    assert (uzbek.name_ru, uzbek.name_en) == ("O'zbek tili", "O'zbek tili")


async def test_the_first_year_group_studies_a_year_later() -> None:
    """ID-1: curriculum 2123 has its own id, name and dates; the subjects match."""
    client = make_client()
    second_year = await client.curriculum_detail(
        await client.login("student01", "password")
    )

    first_year = await client.curriculum_detail(
        await client.login("student16", "password")
    )

    assert (second_year.emis_id, first_year.emis_id) == (2124, 2123)
    assert first_year.name == "ТН, МТН, БТН 2026-2028"
    assert first_year.semesters[0].starts_on == date(2026, 9, 2)
    assert first_year.semesters[0].starts_on.weekday() == (
        second_year.semesters[0].starts_on.weekday()
    )
    assert first_year.start_year is not None
    assert (first_year.start_year.code, first_year.start_year.name) == (
        "2026",
        "2026-2027",
    )
    assert first_year.subjects == second_year.subjects
    assert first_year.semester_subjects == second_year.semester_subjects


async def test_curriculum_endpoints_need_a_valid_token() -> None:
    """ID-7: like every data call, the curriculum is behind the student's token."""
    client = make_client()

    with pytest.raises(EmisAuthError):
        await client.curriculum_detail("garbage")
    with pytest.raises(EmisAuthError):
        await client.curriculum("garbage")


def test_the_sample_result_is_a_fresh_copy_every_time() -> None:
    """SYNC-3: callers may change the dict without touching the fake's data."""
    first = fake_curriculum_result()
    first["name"] = "changed"
    first["edu_subject"].clear()

    second = fake_curriculum_result()

    assert second["name"] == "ТН, МТН, БТН 2025-2027"
    assert len(second["edu_subject"]) == 8

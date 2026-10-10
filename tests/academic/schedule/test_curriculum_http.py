"""HTTP contract of the group curriculum: admin read and sync, student read."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_schedule import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_curriculum import ROUTERS as CURRICULUM_ROUTERS
from app.shared.actor import Role
from app.shared.contracts.emis import EmisAuthFailed, EmisUnavailable
from app.shared.ids import new_id
from tests.academic.schedule.conftest import Api
from tests.academic.schedule.curriculum_builders import (
    ENGLISH,
    MATH,
    PHYSICS,
    SEMESTERS,
    make_curriculum,
    semester_subject,
)
from tests.academic.schedule.env import Env
from tests.conftest import HttpClientFactory
from tests.factories import make_actor

import pytest_asyncio

TOP_LEVEL_KEYS = {
    "emis_curriculum_id",
    "name",
    "speciality",
    "direction",
    "edu_form",
    "language_code",
    "rating_scale",
    "current_semester",
    "fetched_at",
    "semesters",
    "exams",
    "vocational_subjects",
}


@pytest_asyncio.fixture
async def curriculum_api(env: Env, http_client: HttpClientFactory) -> Api:
    """The admin routers and the student curriculum router over the env's services."""
    holder = {"actor": make_actor(Role.ADMIN)}
    client = await http_client(
        [*ADMIN_ROUTERS, *CURRICULUM_ROUTERS],
        {get_actor: lambda: holder["actor"]},
        academic=SimpleNamespace(schedule=env.services, emis_import=env.emis_import),
    )
    return Api(client, holder)


async def _synced_group(env: Env) -> tuple[Any, Any, Any]:
    """A group with one student and a math subject that has only a Russian name."""
    group = await env.group()
    student = await env.student(group)
    math = await env.subject("Математика (наш)", short="Мат", emis_id=MATH)
    env.emis.curriculum_result = make_curriculum()
    await env.emis_import.sync_group_curriculum.execute(group.id)
    env.emis.calls.clear()
    return group, student, math


def _subjects(body: dict[str, Any], semester: int) -> list[dict[str, Any]]:
    found = next(s for s in body["semesters"] if s["number"] == semester)
    subjects: list[dict[str, Any]] = found["subjects"]
    return subjects


# - - - GET /v1/admin/groups/{id}/curriculum - - -


async def test_the_admin_sees_null_before_the_group_has_a_curriculum(
    env: Env, curriculum_api: Api
) -> None:
    """No row: 200 with a JSON null, and no call to EMIS."""
    group = await env.group()
    await env.student(group)

    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )

    assert response.status_code == 200
    assert response.json() is None
    assert env.emis.calls == []


async def test_the_admin_reads_the_stored_curriculum(
    env: Env, curriculum_api: Api
) -> None:
    """The documented shape, semesters sorted, names preferring the subject's own."""
    group, _, math = await _synced_group(env)

    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == TOP_LEVEL_KEYS
    assert body["emis_curriculum_id"] == 2124
    assert body["name"] == "TN, MTN 2025-2027"
    assert body["speciality"] == {
        "uz": "Tabiiy fanlar",
        "ru": "Естественные науки",
        "en": "",
    }
    assert body["direction"] == {
        "emis_id": 312,
        "name": "Umumiy o'rta ta'lim",
        "code": "3010100",
    }
    assert (body["edu_form"], body["language_code"]) == ("Kunduzgi", "uz")
    assert body["rating_scale"] == {"min": 0, "max": 100}
    assert body["current_semester"] == 3
    assert body["fetched_at"].startswith("2026-10-06T09:00:00")
    assert [s["number"] for s in body["semesters"]] == [1, 2, 3, 4]
    assert [s["is_current"] for s in body["semesters"]] == [False, False, True, False]
    assert body["semesters"][0] == {
        "number": 1,
        "starts_on": "2025-09-01",
        "ends_on": "2025-12-27",
        "is_current": False,
        "subjects": [],
    }
    assert body["exams"] == [
        {"name": {"uz": "Yakuniy imtihon", "ru": "", "en": ""}, "study_hours": 12}
    ]
    assert body["vocational_subjects"] == [
        {"name": {"uz": "", "ru": "Профессия", "en": ""}, "study_hours": None}
    ]
    assert _subjects(body, 3) == [
        {
            "subject_id": None,
            "emis_subject_id": ENGLISH,
            "name": {"uz": "Ingliz tili", "ru": "", "en": "English"},
            "subject_type_id": 2,
            "study_hours": 68,
            "class_hours": 50,
            "independent_hours": 18,
            "is_separated": True,
        },
        {
            "subject_id": str(math.id),
            "emis_subject_id": MATH,
            "name": {
                "uz": "Matematika",
                "ru": "Математика (наш)",
                "en": "Mathematics",
            },
            "subject_type_id": 2,
            "study_hours": 68,
            "class_hours": 50,
            "independent_hours": 18,
            "is_separated": False,
        },
        {
            "subject_id": None,
            "emis_subject_id": PHYSICS,
            "name": {"uz": "Fizika", "ru": "Физика", "en": "Physics"},
            "subject_type_id": 2,
            "study_hours": 68,
            "class_hours": 50,
            "independent_hours": 18,
            "is_separated": False,
        },
    ]
    assert [s["emis_subject_id"] for s in _subjects(body, 4)] == [MATH, PHYSICS]
    assert env.emis.calls == []  # reading never goes to EMIS


async def test_a_semester_only_the_subjects_mention_has_null_dates(
    env: Env, curriculum_api: Api
) -> None:
    """Semester 5 has subjects but no dates: it is listed last with null dates."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum(
        semesters=SEMESTERS[2:],
        semester_subjects=(
            semester_subject(5, MATH, make_curriculum().subjects[0].name),
            semester_subject(3, PHYSICS, make_curriculum().subjects[1].name),
        ),
    )
    await env.emis_import.sync_group_curriculum.execute(group.id)

    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )

    semesters = response.json()["semesters"]
    assert [s["number"] for s in semesters] == [3, 4, 5]
    assert semesters[2]["starts_on"] is None and semesters[2]["ends_on"] is None
    assert semesters[1]["subjects"] == []
    assert [s["emis_subject_id"] for s in semesters[2]["subjects"]] == [MATH]


async def test_without_semester_dates_the_current_semester_is_the_groups(
    env: Env, curriculum_api: Api
) -> None:
    """No dates to compare with today: the group's own semester counts."""
    group = await env.group(semester=4)
    await env.student(group)
    env.emis.curriculum_result = make_curriculum(
        semesters=(),
        semester_subjects=(
            semester_subject(3, MATH, make_curriculum().subjects[0].name),
            semester_subject(4, MATH, make_curriculum().subjects[0].name),
        ),
    )
    await env.emis_import.sync_group_curriculum.execute(group.id)

    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )

    body = response.json()
    assert body["current_semester"] == 4
    assert [(s["number"], s["is_current"]) for s in body["semesters"]] == [
        (3, False),
        (4, True),
    ]


async def test_the_current_semester_follows_today(
    env: Env, curriculum_api: Api
) -> None:
    """In January the spring semester is current, whatever the group row says."""
    group, _, _ = await _synced_group(env)
    env.clock.set(dt.datetime(2027, 2, 1, 9, 0, tzinfo=dt.UTC))

    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )

    assert response.json()["current_semester"] == 4


async def test_an_unknown_group_is_404(env: Env, curriculum_api: Api) -> None:
    """The group id must exist."""
    response = await curriculum_api.client.get(
        f"/v1/admin/groups/{new_id()}/curriculum"
    )

    assert response.status_code == 404
    assert response.json()["type"] == "academic/group-not-found"


async def test_only_administration_reads_or_syncs_a_group_curriculum(
    env: Env, curriculum_api: Api
) -> None:
    """Students and teachers get 403 on both admin routes."""
    group = await env.group()
    for role in (Role.STUDENT, Role.TEACHER):
        curriculum_api.as_role(role)

        read = await curriculum_api.client.get(
            f"/v1/admin/groups/{group.id}/curriculum"
        )
        sync = await curriculum_api.client.post(
            f"/v1/admin/groups/{group.id}/curriculum/sync"
        )

        assert (read.status_code, sync.status_code) == (403, 403)
    assert env.emis.calls == []


# - - - POST /v1/admin/groups/{id}/curriculum/sync - - -


async def test_the_admin_sync_reads_emis_and_returns_the_curriculum(
    env: Env, curriculum_api: Api
) -> None:
    """status "synced" and the same view GET returns."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_result = make_curriculum()

    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{group.id}/curriculum/sync"
    )
    read = await curriculum_api.client.get(f"/v1/admin/groups/{group.id}/curriculum")

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"status", "curriculum"}
    assert body["status"] == "synced"
    assert set(body["curriculum"]) == TOP_LEVEL_KEYS
    assert body["curriculum"] == read.json()
    assert len(env.emis.calls) == 1


async def test_the_admin_sync_refreshes_a_curriculum_that_is_already_stored(
    env: Env, curriculum_api: Api
) -> None:
    """The button always asks EMIS again, unlike the one-time fetch."""
    group, _, _ = await _synced_group(env)
    env.emis.curriculum_result = make_curriculum(emis_id=2999)

    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{group.id}/curriculum/sync"
    )

    assert response.json()["status"] == "synced"
    assert response.json()["curriculum"]["emis_curriculum_id"] == 2999
    assert len(env.emis.calls) == 1


async def test_the_admin_sync_of_a_group_without_a_student_answers_no_student(
    env: Env, curriculum_api: Api
) -> None:
    """Nobody to ask: no_student and a null curriculum."""
    group = await env.group()

    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{group.id}/curriculum/sync"
    )

    assert response.status_code == 200
    assert response.json() == {"status": "no_student", "curriculum": None}


async def test_the_admin_sync_keeps_the_old_curriculum_when_no_link_works(
    env: Env, curriculum_api: Api
) -> None:
    """Credentials rejected: no_student, and the stored curriculum is still shown."""
    group, _, _ = await _synced_group(env)
    env.emis.curriculum_error = EmisAuthFailed()

    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{group.id}/curriculum/sync"
    )

    assert response.json()["status"] == "no_student"
    assert response.json()["curriculum"]["emis_curriculum_id"] == 2124


async def test_the_admin_sync_answers_503_when_emis_is_down(
    env: Env, curriculum_api: Api
) -> None:
    """EmisUnavailable goes through the usual error mapping."""
    group = await env.group()
    await env.student(group)
    env.emis.curriculum_error = EmisUnavailable()

    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{group.id}/curriculum/sync"
    )

    assert response.status_code == 503
    assert response.json()["type"] == "emis/unavailable"


async def test_the_admin_sync_of_an_unknown_group_is_404(
    env: Env, curriculum_api: Api
) -> None:
    """The group id must exist."""
    response = await curriculum_api.client.post(
        f"/v1/admin/groups/{new_id()}/curriculum/sync"
    )

    assert response.status_code == 404


# - - - GET /v1/me/curriculum - - -


async def test_a_student_sees_the_curriculum_of_their_group(
    env: Env, curriculum_api: Api
) -> None:
    """Same view as the admin's, found through the student's own group."""
    group, student, _ = await _synced_group(env)
    admin_view = await curriculum_api.client.get(
        f"/v1/admin/groups/{group.id}/curriculum"
    )
    curriculum_api.as_role(Role.STUDENT, user_id=student.id)

    response = await curriculum_api.client.get("/v1/me/curriculum")

    assert response.status_code == 200
    assert response.json() == admin_view.json()
    assert env.emis.calls == []


async def test_a_student_of_a_group_without_a_curriculum_gets_null(
    env: Env, curriculum_api: Api
) -> None:
    """No row yet: a JSON null, and EMIS is not asked by a read."""
    group = await env.group()
    student = await env.student(group)
    curriculum_api.as_role(Role.STUDENT, user_id=student.id)

    response = await curriculum_api.client.get("/v1/me/curriculum")

    assert response.status_code == 200
    assert response.json() is None
    assert env.emis.calls == []


async def test_a_student_without_a_group_gets_null(
    env: Env, curriculum_api: Api
) -> None:
    """A student role with no academic row has nothing to show."""
    curriculum_api.as_role(Role.STUDENT)

    response = await curriculum_api.client.get("/v1/me/curriculum")

    assert response.status_code == 200
    assert response.json() is None


async def test_another_groups_curriculum_is_not_shown_to_a_student(
    env: Env, curriculum_api: Api
) -> None:
    """The student sees their own group's curriculum only."""
    await _synced_group(env)
    other_group = await env.group("3TN1")
    other = await env.student(other_group, first_name="Bobur", last_name="Aliev")
    curriculum_api.as_role(Role.STUDENT, user_id=other.id)

    response = await curriculum_api.client.get("/v1/me/curriculum")

    assert response.json() is None


async def test_only_students_use_the_student_route(
    env: Env, curriculum_api: Api
) -> None:
    """Teachers and administrators get 403 on /v1/me/curriculum."""
    for role in (Role.TEACHER, Role.ADMIN):
        curriculum_api.as_role(role)

        response = await curriculum_api.client.get("/v1/me/curriculum")

        assert response.status_code == 403

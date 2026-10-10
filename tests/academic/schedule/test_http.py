"""HTTP happy paths and error mapping of every B3 route (API contract)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.schedule.group import Group
from app.shared.actor import Role
from tests.academic.schedule.conftest import Api
from tests.academic.schedule.env import Env

PROBLEM = "application/problem+json"
TERM_BODY = {
    "academic_year": "2026-2027",
    "half": 1,
    "starts_on": "2026-09-01",
    "ends_on": "2026-12-25",
    "bells": [
        {
            "period": 1,
            "start": "08:30",
            "end": "09:15",
            "weekdays": [1, 2, 3, 4, 5],
            "source": "manual",
            "emis_start": None,
            "emis_end": None,
        },
        {
            "period": 2,
            "start": "09:25",
            "end": "10:10",
            "weekdays": [1, 2, 3, 4, 5, 6],
            "source": "emis",
            "emis_start": None,
            "emis_end": None,
        },
    ],
    "non_study_days": ["2026-10-12"],
    "moved_days": [{"date": "2026-11-14", "follows_weekday": 1}],
}


NO_CONTROL_PERIODS = {"midterm_1": None, "midterm_2": None, "final": None}

# - - - terms - - -


async def test_terms_can_be_created_listed_and_patched(env: Env, api: Api) -> None:
    """ADM-8: POST, GET and PATCH /v1/admin/terms."""
    created = await api.client.post("/v1/admin/terms", json=TERM_BODY)
    term_id = created.json()["id"]
    listed = await api.client.get("/v1/admin/terms")
    patched = await api.client.patch(f"/v1/admin/terms/{term_id}", json={"half": 2})

    assert created.status_code == 200
    assert created.json() == {
        **TERM_BODY,
        "id": term_id,
        "is_current": True,
        "control_periods": NO_CONTROL_PERIODS,
    }
    assert [t["id"] for t in listed.json()] == [term_id]
    assert patched.json()["half"] == 2 and patched.json()["bells"] == TERM_BODY["bells"]


async def test_control_periods_are_set_on_create_and_replaced_on_patch(
    env: Env, api: Api
) -> None:
    """Administration sets the midterm and final weeks; PATCH replaces them."""
    weeks = {"midterm_1": {"start": "2026-10-19", "end": "2026-10-24"}}
    created = await api.client.post(
        "/v1/admin/terms", json={**TERM_BODY, "control_periods": weeks}
    )
    term_id = created.json()["id"]
    final = {"final": {"start": "2026-12-14", "end": "2026-12-19"}}
    untouched = await api.client.patch(f"/v1/admin/terms/{term_id}", json={"half": 2})
    replaced = await api.client.patch(
        f"/v1/admin/terms/{term_id}", json={"control_periods": {**weeks, **final}}
    )
    reversed_ = await api.client.patch(
        f"/v1/admin/terms/{term_id}",
        json={
            "control_periods": {"final": {"start": "2026-12-19", "end": "2026-12-14"}}
        },
    )

    assert created.json()["control_periods"] == {**NO_CONTROL_PERIODS, **weeks}
    assert untouched.json()["control_periods"] == {**NO_CONTROL_PERIODS, **weeks}
    assert replaced.json()["control_periods"] == {
        **NO_CONTROL_PERIODS,
        **weeks,
        **final,
    }
    assert reversed_.status_code == 422
    assert reversed_.json()["type"] == "academic/term-control-periods-invalid"


async def test_an_overlapping_term_answers_409_with_a_stable_type(
    env: Env, api: Api
) -> None:
    """ACA-4: errors are problem+json with a stable type."""
    await api.client.post("/v1/admin/terms", json=TERM_BODY)

    again = await api.client.post("/v1/admin/terms", json={**TERM_BODY, "half": 2})

    assert again.status_code == 409
    assert again.headers["content-type"].startswith(PROBLEM)
    assert again.json()["type"] == "academic/term-overlap"
    assert again.json()["message_key"] == "academic-term-overlap"


async def test_invalid_bells_answer_422_before_the_use_case(env: Env, api: Api) -> None:
    """API: malformed bodies are rejected by the schema."""
    bad = {
        **TERM_BODY,
        "bells": [{"period": 1, "start": "late", "end": "09:15", "weekdays": [1]}],
    }

    response = await api.client.post("/v1/admin/terms", json=bad)

    assert response.status_code == 422
    assert response.json()["type"] == "common/request-validation"


async def test_admin_routes_need_the_admin_role(env: Env, api: Api) -> None:
    """Auth column: admin."""
    api.as_role(Role.TEACHER)

    response = await api.client.get("/v1/admin/terms")

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"


# - - - groups - - -


async def test_group_routes(env: Env, api: Api) -> None:
    """ADM-6: create, list, open, set curator and head, assign subgroups."""
    teacher = env.teacher()
    created = await api.client.post(
        "/v1/admin/groups",
        json={"name": "2ТН2", "emis_group_id": 3292, "current_semester": 3},
    )
    group_id = created.json()["id"]
    group = await _group_by_id(env, group_id)
    pupil = await env.student(group, first_name="Aliya", last_name="Aliyeva")

    patched = await api.client.patch(
        f"/v1/admin/groups/{group_id}",
        json={"curator_id": str(teacher.id), "head_student_id": str(pupil.id)},
    )
    assigned = await api.client.put(
        f"/v1/admin/groups/{group_id}/subgroups",
        json={"assignments": [{"user_id": str(pupil.id), "subgroup": 2}]},
    )
    detail = await api.client.get(f"/v1/admin/groups/{group_id}")
    listed = await api.client.get("/v1/admin/groups", params={"status": "active"})
    archived = await api.client.get("/v1/admin/groups", params={"status": "archived"})

    assert created.json() == {
        "id": group_id,
        "name": "2TN2",
        "slug": "2tn2",
        "current_semester": 3,
        "status": "active",
        "students_count": 0,
        "subgroups_assigned": 0,
        "unregistered_count": 0,
        "curator": None,
        "head_student": None,
    }
    assert patched.json()["curator"] == {
        "id": str(teacher.id),
        "first_name": "Gulnora",
        "last_name": "Kalandarova",
    }
    assert patched.json()["head_student"]["id"] == str(pupil.id)
    assert assigned.json()["students"] == [
        {
            "user_id": str(pupil.id),
            "first_name": "Aliya",
            "last_name": "Aliyeva",
            "subgroup": 2,
            "status": "active",
            "registered": True,
        }
    ]
    assert (
        detail.json()["emis_group_id"] == 3292
        and detail.json()["subgroups_assigned"] == 1
    )
    assert [g["id"] for g in listed.json()] == [group_id] and archived.json() == []


async def test_patching_null_clears_the_curator_but_a_missing_field_keeps_it(
    env: Env, api: Api
) -> None:
    """API: PATCH {curator_id: null} clears; {} keeps."""
    group = await env.group(curator=env.teacher())

    kept = await api.client.patch(
        f"/v1/admin/groups/{group.id}", json={"status": "active"}
    )
    cleared = await api.client.patch(
        f"/v1/admin/groups/{group.id}", json={"curator_id": None}
    )

    assert kept.json()["curator"] is not None and cleared.json()["curator"] is None


async def test_staff_group_routes_for_the_curator(env: Env, api: Api) -> None:
    """STF-12, UF-STF-10: the curator lists, opens and sets subgroups of the group."""
    teacher = env.teacher()
    group = await env.group("2TN2", curator=teacher)
    await env.group("1TN1", curator=env.teacher("Other", "Teacher"))
    pupil = await env.student(group)
    api.as_role(Role.TEACHER, user_id=teacher.id)

    listed = await api.client.get("/v1/staff/groups")
    detail = await api.client.get(f"/v1/staff/groups/{group.id}")
    assigned = await api.client.put(
        f"/v1/staff/groups/{group.id}/subgroups",
        json={"assignments": [{"user_id": str(pupil.id), "subgroup": 1}]},
    )

    assert [g["id"] for g in listed.json()] == [str(group.id)]
    assert detail.json()["students_count"] == 1
    assert assigned.json()["students"][0]["subgroup"] == 1


async def test_a_teacher_who_does_not_curate_the_group_gets_403(
    env: Env, api: Api
) -> None:
    """UF-STF-10: subgroup assignment by a non-curator is forbidden."""
    group = await env.group(curator=env.teacher())
    pupil = await env.student(group)
    api.as_role(Role.TEACHER)

    detail = await api.client.get(f"/v1/staff/groups/{group.id}")
    assigned = await api.client.put(
        f"/v1/staff/groups/{group.id}/subgroups",
        json={"assignments": [{"user_id": str(pupil.id), "subgroup": 1}]},
    )

    for response in (detail, assigned):
        assert response.status_code == 403
        assert response.json()["type"] == "academic/not-group-curator"


async def test_an_admin_may_use_the_staff_group_routes(env: Env, api: Api) -> None:
    """ADM-6: Administration can override a subgroup through the staff route too."""
    group = await env.group()
    pupil = await env.student(group)

    assigned = await api.client.put(
        f"/v1/staff/groups/{group.id}/subgroups",
        json={"assignments": [{"user_id": str(pupil.id), "subgroup": 2}]},
    )

    assert (
        assigned.status_code == 200 and assigned.json()["students"][0]["subgroup"] == 2
    )


async def test_a_subgroup_other_than_one_or_two_is_a_validation_error(
    env: Env, api: Api
) -> None:
    """ACA-2: only subgroups 1 and 2."""
    group = await env.group()
    pupil = await env.student(group)

    response = await api.client.put(
        f"/v1/admin/groups/{group.id}/subgroups",
        json={"assignments": [{"user_id": str(pupil.id), "subgroup": 3}]},
    )

    assert response.status_code == 422


# - - - subjects - - -


async def test_subject_routes(env: Env, api: Api) -> None:
    """ADM-7: create, list with query, patch."""
    created = await api.client.post(
        "/v1/admin/subjects",
        json={
            "name": {"uz": "Fizika", "ru": "Физика", "en": "Physics"},
            "short_name": "Phys",
            "can_be_divided": True,
        },
    )
    subject_id = created.json()["id"]
    patched = await api.client.patch(
        f"/v1/admin/subjects/{subject_id}",
        json={"emis_subject_id": 77, "short_name": None},
    )
    found = await api.client.get("/v1/admin/subjects", params={"query": "Fizi"})
    missing = await api.client.get("/v1/admin/subjects", params={"query": "zzz"})

    assert created.json() == {
        "id": subject_id,
        "name": {"uz": "Fizika", "ru": "Физика", "en": "Physics"},
        "short_name": "Phys",
        "emis_subject_id": None,
        "can_be_divided": True,
    }
    assert (
        patched.json()["emis_subject_id"] == 77 and patched.json()["short_name"] is None
    )
    assert [s["id"] for s in found.json()] == [subject_id] and missing.json() == []


# - - - rooms - - -


async def test_room_routes(env: Env, api: Api) -> None:
    """ADM-19: list, rename, regenerate PIN, merge, archive."""
    typo = await env.room("1O2")
    right = await env.room("102")
    spare = await env.room("Лаб")

    listed = await api.client.get("/v1/admin/rooms")
    renamed = await api.client.patch(
        f"/v1/admin/rooms/{spare.id}", json={"name": "Lab"}
    )
    new_pin = await api.client.post(f"/v1/admin/rooms/{right.id}/regenerate-pin")
    merged = await api.client.post(
        f"/v1/admin/rooms/{typo.id}/merge", json={"into_room_id": str(right.id)}
    )
    archived = await api.client.post(f"/v1/admin/rooms/{spare.id}/archive")

    rows = {r["slug"]: r for r in listed.json()}
    assert set(rows) == {"1o2", "102", "lab"}
    assert rows["102"]["url"].endswith(f"/102?pin={right.pin}")
    assert rows["102"]["lessons_this_week"] == 0 and rows["102"]["status"] == "active"
    assert renamed.json()["slug"] == "lab" and renamed.json()["name"] == "Lab"
    assert new_pin.json()["pin"] != right.pin and len(new_pin.json()["pin"]) == 6
    assert merged.json()["id"] == str(right.id)
    assert archived.json()["status"] == "archived"


async def test_archiving_a_room_in_use_answers_409(env: Env, api: Api) -> None:
    """ROOM-7: a room with future lessons cannot be archived."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        room=room,
    )

    response = await api.client.post(f"/v1/admin/rooms/{room.id}/archive")

    assert (
        response.status_code == 409
        and response.json()["type"] == "academic/room-in-use"
    )


# - - - timetable - - -


def entry_body(
    term_id: UUID, subject_id: UUID, group_id: UUID, **extra: object
) -> dict[str, object]:
    """A TimetableEntryInput JSON body."""
    body: dict[str, object] = {
        "term_id": str(term_id),
        "weekday": 1,
        "period": 1,
        "week_parity": "every",
        "subject_id": str(subject_id),
        "teacher_id": None,
        "room_name": None,
        "audience": [{"group_id": str(group_id), "subgroup": None}],
        "valid_from": "2026-09-01",
        "valid_to": None,
    }
    body.update(extra)
    return body


async def test_timetable_routes(env: Env, api: Api) -> None:
    """ADM-9: list, create, check, patch, delete, copy."""
    term = await env.term()
    second = await env.term(
        starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30), half=2
    )
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()
    body = entry_body(
        term.id, subject.id, group.id, teacher_id=str(teacher.id), room_name="Кластер"
    )

    created = await api.client.post("/v1/admin/timetable", json=body)
    entry_id = created.json()["id"]
    checked = await api.client.post("/v1/admin/timetable/check", json=body)
    listed = await api.client.get(
        "/v1/admin/timetable",
        params={"term_id": str(term.id), "group_id": str(group.id)},
    )
    patched = await api.client.patch(
        f"/v1/admin/timetable/{entry_id}", json={"period": 2, "room_name": None}
    )
    copied = await api.client.post(
        "/v1/admin/timetable/copy",
        json={"from_term_id": str(term.id), "to_term_id": str(second.id)},
    )
    deleted = await api.client.delete(f"/v1/admin/timetable/{entry_id}")

    assert created.json()["room"]["slug"] == "klaster"
    assert created.json()["subject"] == {
        "id": str(subject.id),
        "name": "Математика",
        "short_name": "Мат",
    }
    assert created.json()["audience"] == [
        {"group_id": str(group.id), "group_name": "2TN2", "subgroup": None}
    ]
    assert created.json()["teacher"]["id"] == str(teacher.id)
    assert [c["kind"] for c in checked.json()["conflicts"]] == [
        "teacher",
        "room",
        "audience",
    ]
    assert [e["id"] for e in listed.json()] == [entry_id]
    assert patched.json()["period"] == 2 and patched.json()["room"] is None
    assert copied.json() == {"created": 1}
    assert deleted.status_code == 204 and deleted.content == b""


async def test_a_conflicting_entry_answers_409_with_the_conflicts(
    env: Env, api: Api
) -> None:
    """ACA-8: 409 carries params.conflicts (type common/conflict)."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    first = await api.client.post(
        "/v1/admin/timetable", json=entry_body(term.id, subject.id, group.id)
    )

    second = await api.client.post(
        "/v1/admin/timetable", json=entry_body(term.id, subject.id, group.id)
    )

    assert second.status_code == 409
    problem = second.json()
    assert problem["type"] == "common/conflict"
    assert problem["params"]["conflicts"] == [
        {
            "kind": "audience",
            "with_entry_id": first.json()["id"],
            "with_lesson_id": None,
            "description": problem["params"]["conflicts"][0]["description"],
            "week_parity": "every",
        }
    ]


# - - - lessons - - -


async def test_lesson_routes(env: Env, api: Api) -> None:
    """ADM-10: create an extra lesson, list with filters, change it."""
    await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()

    created = await api.client.post(
        "/v1/admin/lessons",
        json={
            "date": "2026-10-14",
            "period": 2,
            "subject_id": str(subject.id),
            "teacher_id": str(teacher.id),
            "room_name": "Lab",
            "audience": [{"group_id": str(group.id), "subgroup": None}],
            "topic": "Revision",
        },
    )
    lesson_id = created.json()["id"]
    listed = await api.client.get(
        "/v1/admin/lessons",
        params={
            "from": "2026-10-01",
            "to": "2026-10-31",
            "group_id": str(group.id),
            "status": "scheduled",
        },
    )
    patched = await api.client.patch(
        f"/v1/admin/lessons/{lesson_id}",
        json={"status": "cancelled", "room_name": "Hall"},
    )

    assert created.status_code == 200
    assert (
        created.json()["is_overridden"] is True
        and created.json()["room"]["slug"] == "lab"
    )
    assert (
        listed.json()["items"][0]["id"] == lesson_id
        and listed.json()["next_cursor"] is None
    )
    assert patched.json()["status"] == "cancelled"
    assert patched.json()["changes"] == {
        "status": ["scheduled", "cancelled"],
        "room": ["Lab", "Hall"],
    }


async def test_the_lesson_list_pages_with_a_cursor(env: Env, api: Api) -> None:
    """API: Page<T> with next_cursor."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    for day in (14, 15, 16):
        await env.lesson(
            term,
            day=dt.date(2026, 10, day),
            period=1,
            subject=subject,
            audience=[str(group.id)],
        )

    first = await api.client.get("/v1/admin/lessons", params={"limit": 2})
    second = await api.client.get(
        "/v1/admin/lessons", params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )

    assert len(first.json()["items"]) == 2 and first.json()["next_cursor"]
    assert len(second.json()["items"]) == 1 and second.json()["next_cursor"] is None


# - - - students and import - - -


async def test_student_list_and_csv_import(env: Env, api: Api) -> None:
    """ADM-17: upload, preview, confirm; the new student shows as not registered."""
    group = await env.group("2TN2")
    await env.student(group, first_name="Aliya", last_name="Aliyeva")
    csv = (
        "last_name,first_name,middle_name,group,emis_student_id\n"
        "ALIYEVA,ALIYA,,2ТН2,\n"
        "SIDOROV,SIDOR,,2ТН2,777\n"
    )

    preview = await api.client.post(
        "/v1/admin/students/import",
        files={"file": ("students.csv", csv.encode(), "text/csv")},
    )
    import_id = preview.json()["import_id"]
    confirmed = await api.client.post(f"/v1/admin/students/import/{import_id}/confirm")
    listed = await api.client.get("/v1/admin/students", params={"registered": "false"})
    everyone = await api.client.get(
        "/v1/admin/students", params={"group_id": str(group.id), "limit": 1}
    )

    assert preview.json()["unchanged"] == 1 and preview.json()["changed"] == []
    assert preview.json()["new"] == [
        {
            "line": 3,
            "last_name": "Sidorov",
            "first_name": "Sidor",
            "middle_name": None,
            "group_name": "2TN2",
            "emis_student_id": 777,
            "note": None,
        }
    ]
    assert confirmed.json() == {"created": 1, "updated": 0, "skipped": 1}
    assert [s["last_name"] for s in listed.json()["items"]] == ["Sidorov"]
    assert listed.json()["items"][0]["group"] == {"id": str(group.id), "name": "2TN2"}
    assert listed.json()["items"][0]["registered"] is False
    assert everyone.json()["next_cursor"] is not None


async def test_a_bad_csv_answers_422(env: Env, api: Api) -> None:
    """ADM-17: a file without the required columns is rejected."""
    response = await api.client.post(
        "/v1/admin/students/import",
        files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")},
    )

    assert (
        response.status_code == 422
        and response.json()["type"] == "academic/import-invalid"
    )


async def test_confirming_an_unknown_import_answers_410(env: Env, api: Api) -> None:
    """UF-ADM-14: expired previews answer 410."""
    response = await api.client.post(
        "/v1/admin/students/import/019a0000-0000-7000-8000-000000000000/confirm"
    )

    assert (
        response.status_code == 410
        and response.json()["type"] == "academic/import-expired"
    )


# - - - me and staff timetable - - -


async def test_student_profile_and_timetable(env: Env, api: Api) -> None:
    """WEB-5, WEB-16: GET /v1/me/profile and /v1/me/timetable."""
    term = await env.term()
    subject = await env.subject()
    curator = env.teacher()
    group = await env.group("2TN2", curator=curator, semester=3)
    me = await env.student(group, subgroup=1, first_name="Aliya", last_name="Karimova")
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=curator,
    )
    api.as_role(Role.STUDENT, user_id=me.id)

    profile = await api.client.get("/v1/me/profile")
    timetable = await api.client.get(
        "/v1/me/timetable", params={"from": "2026-10-06", "to": "2026-10-12"}
    )

    assert profile.json() == {
        "user_id": str(me.id),
        "login": "karimova.aliya",
        "first_name": "Aliya",
        "last_name": "Karimova",
        "mailbox": "karimova.aliya@mail.test",
        "group": {"id": str(group.id), "name": "2TN2"},
        "subgroup": 1,
        "curator": {
            "id": str(curator.id),
            "first_name": "Gulnora",
            "last_name": "Kalandarova",
        },
        "head_student": None,
        "current_semester": 3,
        "emis_status": "active",
        "synced_at": None,
    }
    [item] = timetable.json()
    assert item["date"] == "2026-10-07" and item["subject"]["name"] == "Математика"
    assert item["teacher"]["id"] == str(curator.id) and item["status"] == "scheduled"
    assert set(item) == {
        "id",
        "date",
        "period",
        "starts_at",
        "ends_at",
        "subject",
        "teacher",
        "room",
        "audience",
        "status",
        "is_overridden",
        "changes",
        "topic",
        "kind",
        "topic_source",
        "has_homework",
        "attendance_submitted",
    }


async def test_staff_timetable(env: Env, api: Api) -> None:
    """STF-3: GET /v1/staff/timetable."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    api.as_role(Role.TEACHER, user_id=teacher.id)

    response = await api.client.get(
        "/v1/staff/timetable", params={"from": "2026-10-07", "to": "2026-10-07"}
    )

    assert [i["date"] for i in response.json()] == ["2026-10-07"]


async def test_profile_and_timetable_need_the_student_role(env: Env, api: Api) -> None:
    """Auth column: student / teacher."""
    api.as_role(Role.TEACHER)
    assert (await api.client.get("/v1/me/profile")).status_code == 403
    assert (await api.client.get("/v1/me/timetable")).status_code == 403
    api.as_role(Role.STUDENT)
    assert (await api.client.get("/v1/staff/timetable")).status_code == 403


async def test_a_reversed_timetable_range_answers_422(env: Env, api: Api) -> None:
    """API: from after to is rejected."""
    pupil = await env.student(await env.group())
    api.as_role(Role.STUDENT, user_id=pupil.id)

    response = await api.client.get(
        "/v1/me/timetable", params={"from": "2026-10-12", "to": "2026-10-01"}
    )

    assert (
        response.status_code == 422
        and response.json()["type"] == "academic/invalid-date-range"
    )


async def _group_by_id(env: Env, group_id: str) -> Group:
    async with env.uow_factory() as uow:
        group = await uow.groups.get(UUID(group_id))
    assert group is not None
    return group

"""ACA-12, ACA-20, STF-11, STF-13, STF-14, ADM-12: attendance reports."""

import dataclasses
import datetime as dt

from app.modules.academic.domain.classwork.errors import NotCuratorError
from app.shared.base_error import ForbiddenError
from app.shared.contracts.identity import UserStatus
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_result, seed_attendance

import pytest

FROM = DAY - dt.timedelta(days=10)


def rows_by_label(report: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    """Report rows keyed by label."""
    return {row["label"]: row for row in report["rows"]}


async def test_student_attendance_counts_only_lessons_with_taken_attendance(
    env: Env,
) -> None:
    """ACA-12: absence rate excludes lessons where nothing was taken."""
    await seed_attendance(env.maker, env.world)

    page = await env.services.student_attendance.execute(env.student("aziz"), FROM, DAY)

    assert page["from"] == str(FROM)
    assert page["to"] == str(DAY)
    assert page["summary"] == [
        {
            "subject": page["summary"][0]["subject"],
            "absences": 2,
            "excused": 1,
            "lessons": 3,
            "rate": 0.6667,
        }
    ]
    assert page["summary"][0]["subject"]["name"] == "Physics"
    assert page["days"] == [
        {"date": "2026-10-03", "absences": 1},
        {"date": "2026-10-04", "absences": 1},
    ]
    assert page["not_taken"] == 2  # yesterday's math and today's first physics


async def test_student_attendance_lists_missed_lessons_newest_first(env: Env) -> None:
    """UF-WEB-12 4: every missed lesson with date and excused flag."""
    ids = await seed_attendance(env.maker, env.world)

    page = await env.services.student_attendance.execute(env.student("aziz"), FROM, DAY)

    assert [(m["lesson"]["id"], m["excused"]) for m in page["missed"]] == [
        (str(ids["l2"]), False),
        (str(ids["l1"]), True),
    ]


async def test_student_attendance_defaults_to_the_current_term(env: Env) -> None:
    """UF-WEB-12 1: the default period is the term."""
    await seed_attendance(env.maker, env.world)

    page = await env.services.student_attendance.execute(
        env.student("bobur"), None, None
    )

    assert page["from"] == "2026-09-01"
    assert page["to"] == "2026-12-31"
    assert page["summary"][0]["absences"] == 1
    assert page["summary"][0]["lessons"] == 3


async def test_students_without_attendance_data_get_an_empty_page(env: Env) -> None:
    """UF-WEB-12 2a: lessons with no list are "not taken", nothing else."""
    page = await env.services.student_attendance.execute(
        env.student("camila"), FROM, DAY
    )

    assert page["summary"] == []
    assert page["days"] == []
    assert page["missed"] == []
    assert page["not_taken"] == 0


async def test_curator_report_per_student(env: Env) -> None:
    """UF-STF-11 2: per student, excused counted apart, not-taken counted apart."""
    await seed_attendance(env.maker, env.world)

    report = await env.services.group_attendance.execute(
        env.curator, env.world.group_id, "student", FROM, DAY
    )

    rows = rows_by_label(report)
    assert list(rows) == ["Abdullaev Aziz", "Karimov Bobur", "Rakhimova Camila"]
    assert (rows["Abdullaev Aziz"]["absences"], rows["Abdullaev Aziz"]["excused"]) == (
        2,
        1,
    )
    assert rows["Abdullaev Aziz"]["lessons"] == 3
    assert rows["Abdullaev Aziz"]["rate"] == 0.6667
    assert rows["Abdullaev Aziz"]["not_taken"] == 2
    assert rows["Karimov Bobur"]["absences"] == 1
    assert rows["Rakhimova Camila"]["absences"] == 0
    assert rows["Rakhimova Camila"]["rate"] == 0.0


async def test_curator_report_per_subject_day_and_lesson(env: Env) -> None:
    """UF-STF-11 2: the other three views."""
    ids = await seed_attendance(env.maker, env.world)
    curator, group = env.curator, env.world.group_id

    subjects = rows_by_label(
        await env.services.group_attendance.execute(
            curator, group, "subject", FROM, DAY
        )
    )
    days = await env.services.group_attendance.execute(curator, group, "day", FROM, DAY)
    lessons = await env.services.group_attendance.execute(
        curator, group, "lesson", FROM, DAY
    )

    assert subjects["Physics"]["absences"] == 3
    assert subjects["Physics"]["lessons"] == 9
    assert subjects["Physics"]["not_taken"] == 1
    assert subjects["Matematika"]["lessons"] == 0
    assert subjects["Matematika"]["not_taken"] == 1
    assert [(r["key"], r["absences"]) for r in days["rows"][:3]] == [
        ("2026-10-03", 1),
        ("2026-10-04", 2),
        ("2026-10-05", 0),
    ]
    first = lessons["rows"][0]
    assert first["key"] == str(ids["l1"])
    assert first["label"] == "2026-10-03 · 1 · Physics"
    assert first["absences"] == 1


async def test_only_the_curator_or_administration_see_a_group_report(env: Env) -> None:
    """STF-13: curator of the group, or Administration."""
    await seed_attendance(env.maker, env.world)
    with pytest.raises(NotCuratorError):
        await env.services.group_attendance.execute(
            env.other_teacher, env.world.group_id, "student", FROM, DAY
        )

    report = await env.services.group_attendance.execute(
        env.admin, env.world.group_id, "student", FROM, DAY
    )

    assert len(report["rows"]) == 3


async def test_admin_report_per_group_teacher_subject_and_student(env: Env) -> None:
    """UF-ADM-09 1-2: absences and rates per group, student, subject, teacher."""
    await seed_attendance(env.maker, env.world)
    admin = env.admin

    groups = rows_by_label(
        await env.services.attendance_report.execute(admin, "group", FROM, DAY, None)
    )
    teachers = rows_by_label(
        await env.services.attendance_report.execute(admin, "teacher", FROM, DAY, None)
    )
    students = await env.services.attendance_report.execute(
        admin, "student", FROM, DAY, env.world.group_id
    )

    assert groups["2TN2"]["absences"] == 3
    assert groups["2TN2"]["lessons"] == 9
    assert groups["2TN2"]["not_taken"] == 2
    assert teachers["Kalandarova Gulnara"]["absences"] == 3
    assert teachers["Kalandarova Gulnara"]["not_taken"] == 1
    assert teachers["Yusupov Rustam"]["lessons"] == 0
    assert teachers["Yusupov Rustam"]["not_taken"] == 1
    assert len(students["rows"]) == 3


async def test_admin_report_requires_the_admin_role(env: Env) -> None:
    """ADM-12: only Administration."""
    with pytest.raises(ForbiddenError):
        await env.services.attendance_report.execute(
            env.teacher, "group", FROM, DAY, None
        )


async def test_missing_attendance_groups_finished_lessons_by_teacher(env: Env) -> None:
    """UF-ADM-09 3: teachers with lessons not submitted."""
    ids = await seed_attendance(env.maker, env.world)

    rows = await env.services.missing_attendance.execute(env.admin, None, None)

    assert [r["teacher"]["last_name"] for r in rows] == ["Kalandarova", "Yusupov"]
    assert [lesson["id"] for lesson in rows[0]["lessons"]] == [str(ids["today"])]
    assert [lesson["id"] for lesson in rows[1]["lessons"]] == [str(ids["math"])]


async def test_curator_students_are_flagged_by_the_reasons_to_look_at_them(
    env: Env,
) -> None:
    """STF-14: absences above 20 %, a GPA drop, no subgroup."""
    w = env.world
    await seed_attendance(env.maker, w)
    await add_result(env.maker, w.aziz.id, 2, 4.0)
    await add_result(env.maker, w.aziz.id, 1, 4.5)
    await add_result(env.maker, w.bobur.id, 2, 4.4)
    await add_result(env.maker, w.bobur.id, 1, 4.5)
    env.identity.users[w.camila.id] = dataclasses.replace(
        w.camila, status=UserStatus.UNREGISTERED
    )

    students = await env.services.curator_students.execute(env.curator, w.group_id)

    by_name = {s["last_name"]: s for s in students}
    assert by_name["Abdullaev"]["flags"] == ["absences", "gpa_drop"]
    assert by_name["Abdullaev"]["absence_rate"] == 0.6667
    assert by_name["Abdullaev"]["gpa"] == 4.0
    assert by_name["Karimov"]["flags"] == ["absences"]
    assert by_name["Rakhimova"]["flags"] == ["no_subgroup"]
    assert by_name["Rakhimova"]["registered"] is False
    assert by_name["Abdullaev"]["registered"] is True
    assert [s["last_name"] for s in students] == ["Abdullaev", "Karimov", "Rakhimova"]


async def test_reports_export_to_csv_with_bom_and_semicolons(env: Env) -> None:
    """STF-13: export the current view as CSV."""
    await seed_attendance(env.maker, env.world)

    data = await env.services.group_attendance_csv.execute(
        env.curator, env.world.group_id, "student", FROM, DAY
    )
    admin_data = await env.services.attendance_report_csv.execute(
        env.admin, "group", FROM, DAY, None
    )

    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").splitlines()
    assert (
        lines[0]
        == "Name;Absences;Excused;Lessons with attendance;Absence rate, %;Not taken"
    )
    assert lines[1] == "Abdullaev Aziz;2;1;3;66.7;2"
    assert admin_data.decode("utf-8-sig").splitlines()[1] == "2TN2;3;1;9;33.3;2"

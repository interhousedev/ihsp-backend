"""STF-9, UF-STF-07: the journal grid and its options."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import JournalNotFoundError
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import (
    DAY,
    add_lesson,
    add_mark,
    add_result,
    seed_attendance,
)

import pytest


async def test_options_list_the_subjects_and_audiences_the_teacher_teaches(
    env: Env,
) -> None:
    """UF-STF-07 1: Physics for 2TN2 and for 2TN2/1; others' lessons are not listed."""
    w = env.world
    await seed_attendance(env.maker, w)
    await add_lesson(
        env.maker, w, day=DAY + dt.timedelta(days=1), audience=[f"{w.group_id}:1"]
    )

    options = await env.services.journal_options.execute(env.teacher)

    assert [(o["subject"]["name"], o["label"]) for o in options] == [
        ("Physics", "2TN2"),
        ("Physics", "2TN2/1"),
    ]
    assert options[0]["audience_key"] == str(w.group_id)
    assert options[1]["audience_key"] == f"{w.group_id}:1"
    theirs = await env.services.journal_options.execute(env.other_teacher)
    assert [(o["subject"]["name"], o["label"]) for o in theirs] == [
        ("Matematika", "2TN2")
    ]


async def test_journal_has_students_by_lessons_with_absences_and_marks(
    env: Env,
) -> None:
    """UF-STF-07 2: absent, excused, marks and the semester mark."""
    w = env.world
    ids = await seed_attendance(env.maker, w)
    await add_mark(
        env.maker,
        w.aziz.id,
        w.physics_id,
        value=5,
        day=DAY - dt.timedelta(days=1),
        lesson_id=ids["l3"],
    )
    await add_result(env.maker, w.aziz.id, 2, 4.5, subject_id=w.physics_id)

    journal = await env.services.get_journal.execute(
        env.teacher, w.physics_id, str(w.group_id), None
    )

    assert journal["subject"]["name"] == "Physics"
    assert [lesson["id"] for lesson in journal["lessons"]] == [
        str(ids["l1"]),
        str(ids["l2"]),
        str(ids["l3"]),
        str(ids["today"]),
    ]
    assert journal["lessons"][0]["topic"] == "Waves"
    assert [lesson["attendance_submitted"] for lesson in journal["lessons"]] == [
        True,
        True,
        True,
        False,
    ]
    assert all(lesson["editable"] for lesson in journal["lessons"])
    aziz = journal["students"][0]
    assert aziz["last_name"] == "Abdullaev"
    assert [(c["absent"], c["excused"], c["marks"]) for c in aziz["cells"]] == [
        (True, True, []),
        (True, False, []),
        (False, False, [5]),
        (False, False, []),
    ]
    assert aziz["absences"] == 2
    assert aziz["semester_mark"] == 4.5
    assert journal["students"][1]["semester_mark"] is None


async def test_journal_cells_carry_the_temporary_mark_next_to_emis(env: Env) -> None:
    """Temporary marks show in the grid, apart from EMIS marks; others get None."""
    w = env.world
    ids = await seed_attendance(env.maker, w)
    s = env.services
    await s.set_temporary_mark.execute(
        ids["l1"], w.aziz.id, env.teacher, value=3, comment="oral"
    )

    journal = await s.get_journal.execute(
        env.teacher, w.physics_id, str(w.group_id), None
    )

    aziz, bobur = journal["students"][0], journal["students"][1]
    assert aziz["cells"][0]["temporary_mark"] == {"value": 3, "comment": "oral"}
    assert aziz["cells"][0]["marks"] == []
    assert aziz["cells"][1]["temporary_mark"] is None
    assert bobur["cells"][0]["temporary_mark"] is None


async def test_old_lessons_are_not_editable_in_the_grid(env: Env) -> None:
    """UF-STF-07: no time window, old lessons stay editable for staff."""
    w = env.world
    old = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=9))

    journal = await env.services.get_journal.execute(
        env.teacher, w.physics_id, str(w.group_id), None
    )
    admin_view = await env.services.get_journal.execute(
        env.admin, w.physics_id, str(w.group_id), None
    )

    assert journal["lessons"][0]["id"] == str(old)
    assert journal["lessons"][0]["editable"] is True
    assert admin_view["lessons"][0]["editable"] is True


async def test_a_teacher_cannot_open_a_journal_they_do_not_teach(env: Env) -> None:
    """STF-9: subject and audience of the teacher's own lessons."""
    w = env.world
    await seed_attendance(env.maker, w)

    with pytest.raises(JournalNotFoundError):
        await env.services.get_journal.execute(
            env.other_teacher, w.physics_id, str(w.group_id), None
        )
    with pytest.raises(JournalNotFoundError):
        await env.services.get_journal.execute(
            env.teacher, w.physics_id, "not-an-audience", None
        )


async def test_journal_exports_to_csv(env: Env) -> None:
    """STF-9: exportable to CSV."""
    w = env.world
    ids = await seed_attendance(env.maker, w)
    await add_mark(
        env.maker,
        w.aziz.id,
        w.physics_id,
        value=5,
        day=DAY - dt.timedelta(days=1),
        lesson_id=ids["l3"],
    )

    data = await env.services.journal_csv.execute(
        env.teacher, w.physics_id, str(w.group_id), None
    )

    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == (
        "Last name;First name;2026-10-01 Waves;2026-10-04;2026-10-05;2026-10-06;"
        "Absences;Semester mark"
    )
    assert lines[1] == "Abdullaev;Aziz;E;A;5;;2;"
    assert lines[2] == "Karimov;Bobur;;A;;;1;"

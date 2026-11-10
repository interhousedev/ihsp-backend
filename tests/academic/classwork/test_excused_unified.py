"""One excused rule: an approved excuse excuses the lesson in every reader."""

import datetime as dt

from app.modules.academic.domain.classwork.excuse_ref import ExcuseRef
from app.modules.academic.infrastructure.orm.excuse import Excuse, ExcuseTemplate
from app.shared.ids import new_id
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, seed_attendance


async def test_an_approved_excuse_excuses_the_lesson_everywhere(env: Env) -> None:
    """Journal, student attendance and the public query agree on the excuse."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )
    excuse_id = new_id()
    env.coverage.covered[w.aziz.id] = ExcuseRef(excuse_id, "illness", "request")

    journal = await env.services.get_journal.execute(
        env.teacher, w.physics_id, str(w.group_id), None
    )
    page = await env.services.student_attendance.execute(
        env.student("aziz"), DAY - dt.timedelta(days=7), DAY
    )
    items = await env.services.queries.absences(w.aziz.id, None, None)
    by_day = await env.services.student_excuses.execute(
        w.aziz.id, DAY - dt.timedelta(days=7), DAY
    )

    cell = next(
        c
        for s in journal["students"]
        if s["last_name"] == "Abdullaev"
        for c in s["cells"]
        if c["lesson_id"] == str(lesson_id)
    )
    assert cell["excused"] is True
    assert cell["excuse"]["id"] == str(excuse_id)
    missed = next(m for m in page["missed"] if m["lesson"]["id"] == str(lesson_id))
    assert missed["excused"] is True
    assert missed["excuse"]["id"] == str(excuse_id)
    item = next(i for i in items if i["lesson"].id == lesson_id)
    assert item["excused"] is True
    assert item["excuse"]["id"] == str(excuse_id)
    assert by_day[lesson_id]["id"] == str(excuse_id)


async def test_report_counts_follow_the_per_lesson_rule(env: Env) -> None:
    """Aggregate SQL counts agree with the per-lesson list for an approved excuse."""
    w = env.world
    ids = await seed_attendance(env.maker, w)
    template_id, excuse_id = new_id(), new_id()
    l2_day = DAY - dt.timedelta(days=2)
    async with env.maker() as session:
        session.add(
            ExcuseTemplate(
                id=template_id,
                code="illness",
                title={"uz": "x", "ru": "x", "en": "x"},
                requires_document=False,
            )
        )
        await session.flush()
        session.add(
            Excuse(
                id=excuse_id,
                student_id=w.bobur.id,
                origin="curator",
                status="approved",
                template_id=template_id,
                starts_on=l2_day,
                ends_on=l2_day,
                created_by=w.bobur.id,
            )
        )
        await session.commit()
    env.coverage.covered[w.bobur.id] = ExcuseRef(excuse_id, "illness", "curator")
    start = DAY - dt.timedelta(days=10)

    page = await env.services.student_attendance.execute(
        env.student("bobur"), start, DAY
    )
    report = await env.services.group_attendance.execute(
        env.curator, w.group_id, "student", start, DAY
    )

    per_lesson = [m for m in page["missed"] if m["excused"]]
    assert [m["lesson"]["id"] for m in per_lesson] == [str(ids["l2"])]
    row = next(r for r in report["rows"] if r["label"] == "Karimov Bobur")
    assert (row["absences"], row["excused"]) == (1, len(per_lesson))
    assert page["summary"][0]["excused"] == len(per_lesson)

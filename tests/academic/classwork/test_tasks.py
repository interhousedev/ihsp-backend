"""UF-SYS-05, UF-SYS-06: the tasks the scheduler and the schedule module kick."""

import datetime as dt
from types import SimpleNamespace

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.tasks.academic.absence_digests import absence_digests
from app.interfaces.jobs.tasks.academic.lesson_reminders import lesson_reminders
from app.interfaces.jobs.tasks.academic.recompute_due_dates import (
    recompute_due_dates,
)
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, lesson_row, local

import pytest


def test_tasks_are_registered_under_their_contract_names() -> None:
    """§ 3.11: task names are "<module>.<task>"."""
    assert broker.find_task("academic.lesson_reminders") is not None
    assert broker.find_task("academic.absence_digests") is not None
    assert broker.find_task("academic.recompute_due_dates") is not None


@pytest.fixture
def worker_container(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """What bootstrap/worker.py would set: a container with the academic services."""
    container = SimpleNamespace(academic=SimpleNamespace(classwork=env.services))
    monkeypatch.setattr("app.interfaces.jobs.context._container", container)


@pytest.mark.usefixtures("worker_container")
async def test_lesson_reminders_task_queues_the_prompt(env: Env) -> None:
    """UF-SYS-06 2: lessons ending in five minutes get a prompt."""
    await add_lesson(
        env.maker, env.world, starts_at=local(DAY, 13, 20), ends_at=local(DAY, 14, 5)
    )

    result = await lesson_reminders()

    assert result == {"resources": 0, "prompts": 1}


@pytest.mark.usefixtures("worker_container")
async def test_recompute_task_takes_string_ids_from_the_json_payload(env: Env) -> None:
    """UF-SYS-05 4: B3 kicks the task with lesson ids as strings."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY)
    await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=7))
    await env.services.set_homework.execute(given, env.teacher, "Task", None)
    inserted = await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=2))

    changed = await recompute_due_dates([str(inserted)])

    assert changed == 1
    assert (await lesson_row(env.maker, given)).homework_due_date == DAY + dt.timedelta(
        days=2
    )


@pytest.mark.usefixtures("worker_container")
async def test_absence_digests_task_queues_the_curator_digest(env: Env) -> None:
    """WO-4: the job runs the use case; the curator gets one digest."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, day=DAY)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
        work_off_mode="common",
        common_work_off={"text": "Redo"},
    )

    result = await absence_digests()

    assert result == {"queued": 1}

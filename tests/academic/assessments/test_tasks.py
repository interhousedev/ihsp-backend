"""The two scheduled tasks: EMIS suggestions and reminders."""

import datetime as dt
from types import SimpleNamespace

from app.bootstrap.worker import task_modules
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.schedule import CRON_JOBS
from app.interfaces.jobs.tasks.academic.assessment_reminders import (
    assessment_reminders,
)
from app.interfaces.jobs.tasks.academic.generate_assessments import (
    generate_assessments,
)
from tests.academic.assessments.conftest import Env, add_exam_lesson

import pytest

D = dt.date.fromisoformat


def test_tasks_are_registered_and_scheduled_under_their_contract_names() -> None:
    """§ 3.11: task names are "<module>.<task>" and the schedule names real tasks."""
    task_modules()
    jobs = {job.task_name: job.cron for job in CRON_JOBS}

    assert broker.find_task("academic.generate_assessments") is not None
    assert broker.find_task("academic.assessment_reminders") is not None
    assert jobs["academic.generate_assessments"] == "30 2,20 * * *"
    assert jobs["academic.assessment_reminders"] == "30 7 * * *"


@pytest.fixture
def worker_container(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """What bootstrap/worker.py would set: a container with the academic services."""
    container = SimpleNamespace(academic=SimpleNamespace(assessments=env.services))
    monkeypatch.setattr("app.interfaces.jobs.context._container", container)


@pytest.mark.usefixtures("worker_container")
async def test_the_generate_task_returns_what_it_did(env: Env) -> None:
    """The result is the stats dict the use case returns."""
    await add_exam_lesson(env, D("2026-10-21"))

    result = await generate_assessments()

    assert result == {"lessons": 1, "created": 1, "confirmed": 0}


@pytest.mark.usefixtures("worker_container")
async def test_the_reminder_task_queues_the_notifications(env: Env) -> None:
    """On the 12th midterm 1 is 7 days away: 2 subjects x 3 students get a reminder."""
    env.clock.set(dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.UTC))

    result = await assessment_reminders()

    assert result == {"assessments": 2, "notifications": 6}

"""The cron schedule only names tasks that exist, once."""

import re
from pathlib import Path

from app.bootstrap.worker import task_modules
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.schedule import CRON_JOBS, SYNC_SLOTS, scheduled_tasks
from app.interfaces.jobs.tasks.academic.sync_all import SYNC_SLOTS as TASK_SLOTS


def test_sync_slots_match_the_task_module() -> None:
    """The schedule repeats the slots of `academic.sync_all` without importing it."""
    assert SYNC_SLOTS == TASK_SLOTS


def test_every_scheduled_task_is_registered() -> None:
    """A cron entry for a task nobody defined would fail silently every minute."""
    task_modules()  # imports every task module

    missing = [
        job.task_name for job in CRON_JOBS if broker.find_task(job.task_name) is None
    ]

    assert missing == []


def test_schedule_ids_are_unique_and_cron_is_valid() -> None:
    """Each entry has its own stable id and a five-field cron in Tashkent time."""
    tasks = scheduled_tasks()

    assert len({task.schedule_id for task in tasks}) == len(tasks)
    assert all(len((task.cron or "").split()) == 5 for task in tasks)
    assert {task.cron_offset for task in tasks} == {"Asia/Tashkent"}


def test_sync_all_runs_three_times_a_day_with_its_slot() -> None:
    """11:30, 15:00 and 20:00 with the slot as an argument."""
    runs = {
        task.kwargs["slot"]: task.cron
        for task in scheduled_tasks()
        if task.task_name == "academic.sync_all"
    }

    assert runs == {
        "11:30": "30 11 * * *",
        "15:00": "0 15 * * *",
        "20:00": "0 20 * * *",
    }


def test_every_kicked_task_name_is_registered() -> None:
    """A kick of a task nobody defined only logs and the work silently never runs."""
    task_modules()
    pattern = re.compile(
        r"""(?:kick\(\s*|[A-Z_]+_TASK\s*=\s*)["']([a-z_]+\.[a-z_]+)["']"""
    )
    root = Path(__file__).resolve().parents[2] / "app"
    kicked: dict[str, str] = {}
    for path in root.rglob("*.py"):
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            kicked.setdefault(name, path.name)

    unknown = {
        name: src for name, src in kicked.items() if broker.find_task(name) is None
    }

    assert len(kicked) >= 4  # the scan really finds kicks
    assert unknown == {}

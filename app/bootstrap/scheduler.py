"""The scheduler process: exactly one instance sends the cron tasks."""

import argparse
import asyncio

from app.settings import Settings
from app.shared.logging import configure_logging

from taskiq.cli.scheduler.args import SchedulerArgs
from taskiq.cli.scheduler.run import run_scheduler

SCHEDULER = "app.interfaces.jobs.broker:scheduler"


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Send the tasks of `app.interfaces.jobs.schedule` at their time."""
    configure_logging(settings.log_level, json_logs=settings.env == "prod")
    scheduler_args = SchedulerArgs(
        scheduler=SCHEDULER, modules=[], configure_logging=False
    )
    asyncio.run(run_scheduler(scheduler_args))
    return 0

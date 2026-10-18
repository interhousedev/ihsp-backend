"""The worker process: a taskiq worker over every task module."""

import argparse
import importlib
import pkgutil

import app.interfaces.jobs.tasks as tasks_package
from app.settings import Settings
from app.shared.observability import init_observability

from taskiq.cli.worker.args import WorkerArgs
from taskiq.cli.worker.run import run_worker

BROKER = "app.interfaces.jobs.broker:broker"
RUNTIME_MODULE = "app.bootstrap.worker_runtime"
DEFAULT_WORKERS = 2


def task_modules() -> list[str]:
    """Dotted names of every task module (one task per file)."""
    names = [
        info.name
        for info in pkgutil.walk_packages(
            tasks_package.__path__, prefix=f"{tasks_package.__name__}."
        )
        if not info.ispkg
    ]
    for name in names:
        importlib.import_module(name)  # fail fast in the parent on a broken module
    return sorted(names)


def worker_count(extra: list[str]) -> int:
    """`--workers N` after the process name; default two worker processes."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return int(parser.parse_known_args(extra)[0].workers)


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the taskiq worker (it starts its own child processes)."""
    init_observability(settings, "worker")
    worker_args = WorkerArgs(
        broker=BROKER,
        modules=[RUNTIME_MODULE, *task_modules()],
        workers=worker_count(args.extra),
        configure_logging=True,
        shutdown_timeout=30,
    )
    return run_worker(worker_args) or 0

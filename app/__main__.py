"""Command line: `python -m app <process>`."""

import argparse
import importlib
import sys
from collections.abc import Sequence

from app.settings import load_settings

PROCESSES = (
    "all",
    "identity",
    "api",
    "bot",
    "mail",
    "worker",
    "scheduler",
    "migrate",
    "create-user",
    "seed-demo",
)
NOT_WIRED_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    """Create the parser with one sub-command per process."""
    parser = argparse.ArgumentParser(prog="python -m app")
    sub = parser.add_subparsers(dest="process", required=True)
    for name in PROCESSES:
        command = sub.add_parser(name, help=f"run the {name} process")
        if name == "create-user":
            command.add_argument("--role", required=True)
            command.add_argument("--login", required=True)
            command.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to app.bootstrap.<process>:run(settings, args)."""
    args, extra = build_parser().parse_known_args(argv)
    args.extra = extra  # flags a process parses itself
    module_name = f"app.bootstrap.{args.process.replace('-', '_')}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        sys.stderr.write(f"{args.process} is not wired yet\n")
        return NOT_WIRED_EXIT_CODE
    settings = load_settings()
    settings.require_production_ready(args.process)
    result: int | None = module.run(settings, args)
    return result or 0


if __name__ == "__main__":
    sys.exit(main())

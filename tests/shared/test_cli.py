"""python -m app <process>."""

import argparse
import importlib
import sys
from types import ModuleType
from typing import Any

from app import __main__ as cli
from app.settings import Settings

import pytest


def test_every_process_is_a_subcommand() -> None:
    """§ 2.1: all, identity, api, bot, mail, worker, scheduler, migrate, ..."""
    parser = cli.build_parser()

    for name in cli.PROCESSES:
        extra = ["--role", "admin", "--login", "a", "--email", "a@b.c"]
        argv = [name, *(extra if name == "create-user" else [])]
        assert parser.parse_args(argv).process == name


def test_a_process_without_a_bootstrap_exits_with_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A process that is not wired yet says so and exits with 2."""

    def missing(name: str) -> ModuleType:
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(importlib, "import_module", missing)

    code = cli.main(["bot"])

    assert code == 2
    assert "bot is not wired yet" in capsys.readouterr().err


def test_the_bootstrap_run_function_gets_settings_and_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch goes to app.bootstrap.<name>:run(settings, args); dashes become _."""
    calls: list[tuple[Settings, argparse.Namespace]] = []
    fake = ModuleType("app.bootstrap.seed_demo")

    def run(settings: Settings, args: argparse.Namespace) -> int:
        calls.append((settings, args))
        return 0

    fake.run = run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.bootstrap.seed_demo", fake)

    code = cli.main(["seed-demo", "--months", "3"])

    assert code == 0
    assert calls[0][1].process == "seed-demo"
    assert calls[0][1].extra == ["--months", "3"]


def test_a_broken_import_inside_a_bootstrap_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a missing bootstrap module means 'not wired'."""

    def broken(name: str) -> Any:
        raise ModuleNotFoundError(name="some_missing_library")

    monkeypatch.setattr(importlib, "import_module", broken)

    with pytest.raises(ModuleNotFoundError):
        cli.main(["api"])

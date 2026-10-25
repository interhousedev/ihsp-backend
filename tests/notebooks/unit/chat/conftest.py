"""Fixtures of the chat tests: the chat services and cores with other settings."""

import dataclasses
from datetime import UTC, datetime
from typing import Any

from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_chat import ChatServices, build_chat
from app.modules.notebooks.wiring_core import CoreOverrides, NotebooksCore, build_core
from app.shared.actor import Actor, Role
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import CoreFactory

import pytest


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time.

    The budget session window expires at `now + 5 h` through Redis `EXPIREAT`,
    and Redis drops a key whose expiry is already in the past, so the default
    moment of 2026-10-06 would erase the session counters once that day is over.
    """
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def chat(core: NotebooksCore) -> ChatServices:
    """The chat use cases over the default test core."""
    return build_chat(core)


@pytest.fixture
def make_core(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> CoreFactory:
    """Build a core with other settings, another user locale or another gateway."""

    def build(
        *,
        locale: str = "en",
        gateway: ScriptedLlm | None = None,
        notebooks: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
    ) -> NotebooksCore:
        settings = module_deps.settings
        updates: dict[str, Any] = {}
        if notebooks:
            updates["notebooks"] = settings.notebooks.model_copy(update=notebooks)
        if limits:
            updates["limits"] = settings.limits.model_copy(update=limits)
        deps = dataclasses.replace(
            module_deps, settings=settings.model_copy(update=updates)
        )
        users = [
            dataclasses.replace(make_user(Role.STUDENT, locale=locale), id=a.user_id)
            for a in (student, other_student)
        ]
        return build_core(
            deps,
            gateway=gateway or scripted_llm,
            identity=FakeIdentity(*users),  # type: ignore[arg-type]
            overrides=CoreOverrides(uow_factory=uow_factory),
        )

    return build

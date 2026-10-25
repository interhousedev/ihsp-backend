"""Fixtures of the web search tests: the notebooks core over the real search service."""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import CoreOverrides, NotebooksCore, build_core
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import FakeIdentity
from tests.fakes.ai.web_search import WebRig
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.llm import ScriptedLlm

import pytest

WebCore = Callable[..., tuple[NotebooksCore, WebRig]]


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time (the budget keys expire in Redis)."""
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def make_web_core(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
) -> WebCore:
    """Build a core whose web search is the real service over scripted fakes."""

    def build(
        *,
        limits: dict[str, Any] | None = None,
        features: dict[str, bool] | None = None,
        with_search: bool = True,
    ) -> tuple[NotebooksCore, WebRig]:
        settings = module_deps.settings
        updates: dict[str, Any] = {}
        if limits:
            updates["limits"] = settings.limits.model_copy(update=limits)
        if features:
            updates["features"] = settings.features.model_copy(update=features)
        deps = dataclasses.replace(
            module_deps, settings=settings.model_copy(update=updates)
        )
        web = WebRig.build(deps.settings, deps.clock)
        core = build_core(
            deps,
            gateway=scripted_llm,
            identity=cast(IdentityDirectory, identity),
            overrides=CoreOverrides(uow_factory=uow_factory),
            web_search=web.service if with_search else None,
        )
        return core, web

    return build

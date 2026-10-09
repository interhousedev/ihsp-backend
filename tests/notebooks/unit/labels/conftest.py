"""Fixtures of the topic label tests: the label use cases over the test fakes."""

import dataclasses
from datetime import UTC, datetime

from app.modules.notebooks.domain.entities import Notebook, Source, SourceGuide
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_labels import LabelsServices, build_labels
from app.shared.actor import Actor, Role
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.sources.support import HookedLlm

import pytest

GUIDE = SourceGuide(
    summary="Plants turn light into sugar in the chloroplasts.",
    key_topics=["Photosynthesis", "Chloroplast"],
    questions=["Where?"],
)


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock close to the real time (budget windows expire in Redis)."""
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def scripted_llm() -> HookedLlm:
    """The light model: scripted answers; a hook may change things while it works."""
    return HookedLlm()


@pytest.fixture
def user_locale() -> str:
    """The locale of both students; parametrize it to test another language."""
    return "en"


@pytest.fixture
def identity(student: Actor, other_student: Actor, user_locale: str) -> FakeIdentity:
    """Users for the two students, with the locale of `user_locale`."""
    users = [
        dataclasses.replace(
            make_user(Role.STUDENT, locale=user_locale), id=actor.user_id
        )
        for actor in (student, other_student)
    ]
    return FakeIdentity(*users)


@pytest.fixture
def sleeps() -> list[float]:
    """The pauses between provider retries (nobody really sleeps)."""
    return []


@pytest.fixture
def labels(core: NotebooksCore, sleeps: list[float]) -> LabelsServices:
    """The label use cases over the test core."""

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return build_labels(core, sleep=sleep)


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """An empty notebook of the student."""
    return await make_notebook(uow_factory, student.user_id, title="Biology")


@pytest.fixture
async def their_notebook(uow_factory: UowFactory, other_student: Actor) -> Notebook:
    """A notebook of the other student."""
    return await make_notebook(uow_factory, other_student.user_id, title="Chemistry")


@pytest.fixture
async def source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready, selected source with a guide."""
    return await make_source(uow_factory, notebook, title="Biology 10", guide=GUIDE)

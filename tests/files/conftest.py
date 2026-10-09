"""Fixtures of the files tests."""

from collections.abc import Callable

from app.shared.actor import Actor, Role
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker

import pytest


@pytest.fixture
def fakes(clock: FixedClock, kicker: FakeTaskKicker) -> FilesFakes:
    """The files module over in-memory adapters."""
    return build_files_fakes(clock, kicker)


@pytest.fixture
def student(make_actor: Callable[..., Actor]) -> Actor:
    """A student."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher (staff scope, 10 GB)."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """An administrator."""
    return make_actor(Role.ADMIN)


@pytest.fixture
def librarian(make_actor: Callable[..., Actor]) -> Actor:
    """A librarian (a student who runs the library)."""
    return make_actor(Role.STUDENT, Role.LIBRARIAN)

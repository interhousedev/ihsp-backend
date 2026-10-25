"""Fixtures of the notebook CRUD and lifecycle tests."""

import dataclasses

from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import (
    NotebooksLifecycleServices,
    build_notebooks,
)
from app.shared.actor import Actor, Role
from tests.fakes.ai.contracts import FakeIdentity, make_user

import pytest


@pytest.fixture
def user_locale() -> str:
    """The locale of both students; parametrize it to test another language."""
    return "en"


@pytest.fixture
def identity(student: Actor, other_student: Actor, user_locale: str) -> FakeIdentity:
    """Users for the two students, with the locale of the `user_locale` fixture."""
    users = [
        dataclasses.replace(
            make_user(Role.STUDENT, locale=user_locale), id=actor.user_id
        )
        for actor in (student, other_student)
    ]
    return FakeIdentity(*users)


@pytest.fixture
def lifecycle(core: NotebooksCore) -> NotebooksLifecycleServices:
    """The use cases and jobs under test, over the test fakes."""
    return build_notebooks(core)

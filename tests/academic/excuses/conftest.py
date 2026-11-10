"""Fixtures of the excuse tests."""

from tests.fakes.academic.excuses.world import ExcuseWorld

import pytest


@pytest.fixture
def world() -> ExcuseWorld:
    """A fresh world."""
    return ExcuseWorld()

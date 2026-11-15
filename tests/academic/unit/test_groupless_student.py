"""A student without a group (Student.group_id is None) is handled, not crashed on."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.academic.application.curriculum.get_curriculum import (
    GetMyCurriculum,
)
from app.modules.academic.domain.schedule.student import Student
from app.shared.actor import Actor
from tests.fakes.clock import FixedClock


async def test_my_curriculum_is_none_without_a_group() -> None:
    user_id = uuid4()

    class Students:
        async def get(self, uid: UUID) -> Student:
            return Student(user_id=uid, group_id=None)

    class Groups:
        async def get(self, gid: UUID) -> None:
            raise AssertionError("must not look up a group for None")

    uow = SimpleNamespace(students=Students(), groups=Groups())

    @asynccontextmanager
    async def factory():
        yield uow

    use_case = GetMyCurriculum(factory, FixedClock())  # type: ignore[arg-type]
    actor = Actor(user_id=user_id, roles=frozenset())  # type: ignore[call-arg]
    assert await use_case.execute(actor) is None

"""The admin view of the request registry."""

from uuid import uuid4

from app.modules.ai.application.publish_requests import RequestPublisher
from app.modules.ai.application.request_admin import RequestAdmin
from app.modules.ai.domain.prompt_registry import PromptSlot, PromptVersion
from app.modules.ai.domain.requests import AiRequestNotFoundError, AiRequestSpec
from app.shared.actor import Actor, Role
from tests.fakes.ai.requests import (
    FakePromptDefaults,
    FakePromptVersions,
    FakePublishUnit,
    FakeRequests,
)
from tests.fakes.clock import FixedClock

import pytest

ADMIN = Actor(user_id=uuid4(), roles=frozenset({Role.ADMIN}))


def slot(text: str) -> PromptSlot:
    """The quiz slot with the given built-in."""
    return PromptSlot("studio_quiz", "studio", "Quiz", text)


def spec(text: str, id: str = "notebooks.studio_quiz.generate") -> AiRequestSpec:
    """A declared request over the quiz slot."""
    return AiRequestSpec(
        id=id, owner_app="notebooks", task="studio_quiz", template=slot(text)
    )


class World:
    """Stores plus a publisher and the admin view over them."""

    def __init__(self) -> None:
        """Fresh stores."""
        self.prompts = FakePromptVersions()
        self.defaults = FakePromptDefaults()
        self.requests = FakeRequests()
        audits: list = []

        def unit() -> FakePublishUnit:
            return FakePublishUnit(self.prompts, self.defaults, self.requests, audits)

        self.publisher = RequestPublisher(unit, FixedClock())
        self.admin = RequestAdmin(unit)

    async def publish(self, text: str, *specs: AiRequestSpec) -> None:
        """Publish the slot text and the specs."""
        await self.publisher.publish([slot(text)], list(specs or [spec(text)]))


async def test_list_and_get_report_the_active_and_code_versions() -> None:
    """Fresh from code: the built-in is active (0) and nothing changed."""
    w = World()
    await w.publish("v1 text")

    items = await w.admin.list(ADMIN)
    one = await w.admin.get(ADMIN, "notebooks.studio_quiz.generate")

    assert [i.id for i in items] == [one.id]
    assert one.pipeline == "studio" and one.template_id == "studio_quiz/studio"
    assert (one.active_version, one.code_version) == (0, 0)
    assert one.code_changed_since_active is False


async def test_admin_text_older_than_a_code_change_is_flagged() -> None:
    """An administrator's active text stays; the request says the code moved on."""
    w = World()
    await w.publish("v1 text")
    w.prompts.rows.append(
        PromptVersion(
            id=uuid4(),
            task="studio_quiz",
            name="studio",
            locale="",
            version=1,
            text="mine",
            hash="h",
            active=True,
            created_at=FixedClock().now(),
            source="admin",
        )
    )
    await w.publish("v2 text")

    one = await w.admin.get(ADMIN, "notebooks.studio_quiz.generate")

    assert one.active_version == 1 and one.code_version == 2
    assert one.code_changed_since_active is True


async def test_filters_retired_and_unknown_ids() -> None:
    """Retired requests are hidden unless asked; unknown ids are 404."""
    w = World()
    await w.publish("t", spec("t"), spec("t", "notebooks.studio_quiz.other"))
    await w.publish("t", spec("t"))

    visible = [i.id for i in await w.admin.list(ADMIN)]
    everything = [i.id for i in await w.admin.list(ADMIN, include_retired=True)]
    by_owner = await w.admin.list(ADMIN, owner_app="lms")

    assert visible == ["notebooks.studio_quiz.generate"]
    assert len(everything) == 2 and by_owner == []
    with pytest.raises(AiRequestNotFoundError):
        await w.admin.get(ADMIN, "notebooks.nothing.here")

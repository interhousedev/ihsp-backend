"""The api start publishes the prompt defaults and the request registry once."""

from types import SimpleNamespace

from app.modules.ai.application.publish_requests import RequestPublisher
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.ai.domain.requests import AiRequestSpec
from app.modules.ai.wiring import publish_prompts_on_startup
from tests.fakes.ai.requests import (
    FakePromptDefaults,
    FakePromptVersions,
    FakePublishUnit,
    FakeRequests,
)
from tests.fakes.clock import FixedClock

SLOT = PromptSlot("studio_quiz", "main", "Quiz", "Write a quiz.")
SPEC = AiRequestSpec(
    id="notebooks.studio_quiz.main",
    owner_app="notebooks",
    task="studio_quiz",
    template=SLOT,
)


class Registry:
    """Only the slot list is read."""

    def slots(self) -> list[PromptSlot]:
        """The slots."""
        return [SLOT]


def services() -> tuple[SimpleNamespace, FakeRequests]:
    """Prompt services over in-memory stores."""
    prompts, defaults, requests = (
        FakePromptVersions(),
        FakePromptDefaults(),
        FakeRequests(),
    )
    publisher = RequestPublisher(
        lambda: FakePublishUnit(prompts, defaults, requests, []), FixedClock()
    )
    return (
        SimpleNamespace(publisher=publisher, registry=Registry(), catalog=(SPEC,)),
        requests,
    )


async def test_startup_publishes_the_catalog() -> None:
    """The declared request lands in the registry."""
    prompts, requests = services()

    await publish_prompts_on_startup(prompts, True)  # type: ignore[arg-type]

    assert set(requests.rows) == {SPEC.id}


async def test_the_setting_turns_publishing_off() -> None:
    """With the setting off nothing is written."""
    prompts, requests = services()

    await publish_prompts_on_startup(prompts, False)  # type: ignore[arg-type]

    assert requests.rows == {}


async def test_a_second_start_with_the_same_code_adds_no_version() -> None:
    """Publishing twice leaves one registry row and no prompt version."""
    prompts, requests = services()

    await publish_prompts_on_startup(prompts, True)  # type: ignore[arg-type]
    await publish_prompts_on_startup(prompts, True)  # type: ignore[arg-type]

    assert len(requests.rows) == 1
    assert prompts.publisher.uow_factory().prompts.rows == []

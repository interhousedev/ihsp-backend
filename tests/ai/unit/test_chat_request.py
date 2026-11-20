"""A chat turn runs as its registered AI request (the ledger reads the context)."""

from typing import Any

from app.bootstrap.adapters.prompt_slots import prompt_slots
from app.modules.ai.application.prompt_registry import PromptRegistry
from app.modules.ai.application.request_context import RequestCtx, current_request
from app.modules.ai.application.requests import AiRequests
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.requests import build_catalog
from app.modules.ai.wiring import AI_REQUESTS
from tests.ai.conftest import HarnessFactory
from tests.fakes.ai.llm import ScriptedLlm


class _NoVersions:
    """The registry reads no stored versions."""

    async def active(self) -> list:
        """Nothing."""
        return []


class SpyLlm(ScriptedLlm):
    """Records the request context at the moment of each model call."""

    def __init__(self) -> None:
        """Start with no recorded contexts."""
        super().__init__()
        self.seen: list[RequestCtx | None] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        """Note the context, then answer as the scripted model does."""
        self.seen.append(current_request.get())
        return await super().complete(**kwargs)


def requests() -> AiRequests:
    """The real chat requests over the real slots."""
    slots = prompt_slots()
    return AiRequests(
        build_catalog(slots, AI_REQUESTS), PromptRegistry(slots, _NoVersions())
    )


async def test_student_turn_runs_inside_its_request(
    make_harness: HarnessFactory,
) -> None:
    """A student turn's model call sees `ai.student_chat.turn` on the pipeline."""
    spy = SpyLlm()
    h = make_harness(llm=spy, requests=requests())
    chat = await h.new_chat()

    await h.say(chat.id, "Hello")

    assert spy.seen == [RequestCtx("ai.student_chat.turn", "chat")]
    assert current_request.get() is None


async def test_admin_turn_uses_the_admin_request(make_harness: HarnessFactory) -> None:
    """The administration assistant has its own request id."""
    spy = SpyLlm()
    h = make_harness(llm=spy, requests=requests())
    chat = await h.new_chat(assistant=Assistant.ADMIN)

    await h.say(chat.id, "Hello", actor=h.admin)

    assert spy.seen[0] is not None and spy.seen[0].request_id == "ai.admin_chat.turn"


async def test_without_requests_the_turn_has_no_context(
    make_harness: HarnessFactory,
) -> None:
    """The module still works unwired: the ledger just has no request id."""
    spy = SpyLlm()
    h = make_harness(llm=spy)
    chat = await h.new_chat()

    await h.say(chat.id, "Hello")

    assert spy.seen == [None]

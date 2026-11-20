"""AiRequests: argument validation, rendering, the request context and the catalog."""

from uuid import uuid4

from app.modules.ai.application.prompt_registry import PromptRegistry
from app.modules.ai.application.request_context import current_request
from app.modules.ai.application.requests import AiRequests, RenderedRequest
from app.modules.ai.domain.prompt_registry import PromptSlot, PromptVersion
from app.modules.ai.domain.requests import (
    AiRequestArgsInvalidError,
    AiRequestNotFoundError,
    AiRequestSpec,
)
from tests.fakes.clock import FixedClock

import pytest

SLOT = PromptSlot(
    "studio_quiz", "studio", "Quiz", "Write in {language}.", template=True
)
SPEC = AiRequestSpec(
    id="notebooks.studio_quiz.generate",
    owner_app="notebooks",
    task="studio_quiz",
    template=SLOT,
    args_schema={
        "type": "object",
        "properties": {"language": {"type": "string"}},
        "required": ["language"],
    },
    tools=("search_web",),
)


class Loader:
    """Active versions the registry reads."""

    def __init__(self, versions: list[PromptVersion] | None = None) -> None:
        """Keep the versions."""
        self.versions = versions or []

    async def active(self) -> list[PromptVersion]:
        """Every active version."""
        return self.versions


def requests(versions: list[PromptVersion] | None = None) -> AiRequests:
    """An AiRequests over the spec and a registry."""
    return AiRequests([SPEC], PromptRegistry([SLOT], Loader(versions)))


async def test_run_validates_renders_and_sets_the_context() -> None:
    """The call sees the rendered text and the request context; it is reset after."""
    seen = {}

    async def call(rendered: RenderedRequest):
        seen["ctx"] = current_request.get()
        seen["text"] = rendered.text
        seen["version"] = rendered.version
        return "ok"

    result = await requests().run(SPEC.id, {"language": "uz"}, locale="uz", call=call)

    assert result == "ok"
    assert seen["ctx"].request_id == SPEC.id and seen["ctx"].pipeline == "studio"
    assert seen["text"] == "Write in uz." and seen["version"] == 0
    assert current_request.get() is None


async def test_run_uses_the_active_version() -> None:
    """An active admin version is the text the request renders."""
    active = PromptVersion(
        id=uuid4(),
        task="studio_quiz",
        name="studio",
        locale="",
        version=4,
        text="Reply in {language}!",
        hash="h",
        active=True,
        created_at=FixedClock().now(),
    )

    async def call(rendered: RenderedRequest):
        return rendered.text, rendered.version

    assert await requests([active]).run(
        SPEC.id, {"language": "ru"}, locale="ru", call=call
    ) == ("Reply in ru!", 4)


async def test_bad_arguments_never_reach_the_call() -> None:
    """Invalid arguments raise before the call runs and leave no context."""
    ran = []

    async def call(rendered: RenderedRequest):
        ran.append(1)

    with pytest.raises(AiRequestArgsInvalidError) as caught:
        await requests().run(SPEC.id, {}, locale="uz", call=call)

    assert "language: required" in str(caught.value)
    assert ran == [] and current_request.get() is None


async def test_unknown_request_is_not_found() -> None:
    """An id nobody declared is a lookup error."""
    with pytest.raises(AiRequestNotFoundError):
        requests().spec("notebooks.nothing.here")


async def test_context_resets_when_the_call_fails() -> None:
    """An exception inside the call still clears the context."""

    async def call(rendered: RenderedRequest):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await requests().run(SPEC.id, {"language": "en"}, locale="en", call=call)

    assert current_request.get() is None


async def test_scope_restricts_tools_to_the_spec() -> None:
    """Only the tools the spec lists stay in the offered list."""
    async with requests().scope(SPEC.id, {"language": "en"}, locale="en") as rendered:
        offered = [
            {"name": "search_web"},
            {"name": "send_mail"},
        ]
        assert rendered.allowed_tools(offered) == [{"name": "search_web"}]

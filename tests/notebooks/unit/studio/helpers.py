"""Helpers of the Studio tests: sample texts, a model that can be interrupted."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Artifact, Notebook
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from tests.fakes.notebooks.llm import ScriptedLlm

# Four passages of about 60 tokens each: enough for the "no content" threshold.
SOURCE_TEXTS = (
    "Photosynthesis is the process by which green plants turn light energy into "
    "chemical energy stored in glucose, and it takes place in the chloroplasts.",
    "The light reactions happen in the thylakoid membranes. Water is split and "
    "oxygen is released as a by-product of this first stage of photosynthesis.",
    "The Calvin cycle uses carbon dioxide together with the energy carriers ATP "
    "and NADPH to build sugar molecules in the stroma of the chloroplast.",
    "Chlorophyll is the green pigment that absorbs red and blue light. It reflects "
    "green light, which is why the leaves of most plants look green to us.",
)
Build = Callable[..., StudioServices]
BAD_REPORT = {"title": "Too short", "markdown": "This report is far too short."}


def big_texts() -> tuple[str, ...]:
    """Twelve passages of 700 characters: about 3 000 tokens in all."""
    return tuple(
        f"Passage number {n} explains the topic {n} of the lesson in detail. " * 10
        for n in range(1, 13)
    )


class HookedLlm(ScriptedLlm):
    """A scripted model that runs a coroutine before each JSON call.

    The hook cancels, renames or stalls an output while its job waits for the model.
    """

    def __init__(self) -> None:
        """Start without a hook."""
        super().__init__()
        self.before_json: Callable[[], Awaitable[None]] | None = None

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """Run the hook, then answer like `ScriptedLlm`."""
        if self.before_json is not None:
            await self.before_json()
        return await super().complete_json(**kwargs)


async def stored(uow_factory: UowFactory, artifact_id: UUID) -> Artifact:
    """Read an output from the database (with its content)."""
    async with uow_factory() as uow:
        found = await uow.artifacts.get(artifact_id)
    assert found is not None
    return found


async def generate(
    studio: StudioServices,
    uow_factory: UowFactory,
    actor: Actor,
    notebook: Notebook,
    kind: ArtifactKind,
    options: Mapping[str, Any] | None = None,
    prompt: str | None = None,
) -> Artifact:
    """Request an output, run its job and return the stored result."""
    queued = await studio.request_artifact.execute(
        actor, notebook.id, kind, options or {}, prompt
    )
    await studio.generate_artifact.execute(queued.id)
    return await stored(uow_factory, queued.id)

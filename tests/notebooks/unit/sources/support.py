"""Builders and readers shared by the source tests."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Passage, Source
from app.modules.notebooks.domain.source_input import SourceInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.llm import ScriptedLlm

GUIDE = {
    "summary": "Plants turn light into sugar.",
    "key_topics": ["Photosynthesis", "Chloroplast"],
    "questions": ["Where does it happen?", "What is made?", "Why is it green?"],
}
SUMMARY = {
    "title": "Plant energy",
    "emoji": "🌱",
    "summary": "**Light** becomes sugar in the leaf.",
    "key_topics": ["Photosynthesis", "Chlorophyll"],
    "suggested_questions": ["Where does it happen?"],
}
PROCESS_TASK = "notebooks.process_source"
GUIDE_TASK = "notebooks.build_source_guide"


class HookedLlm(ScriptedLlm):
    """A scripted model that runs a coroutine before each JSON call.

    The hook changes the notebook while a guide or a summary waits for the model.
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


async def add_one(
    sources: SourcesServices, actor: Actor, notebook: Notebook, item: SourceInput
) -> Source:
    """Add one item that must be accepted."""
    result = await sources.add_sources.execute(actor, notebook.id, [item])
    assert result.rejected == []
    return result.items[0]


async def add_ready(
    sources: SourcesServices,
    uow_factory: UowFactory,
    actor: Actor,
    notebook: Notebook,
    item: SourceInput,
) -> Source:
    """Add one item and run the processing job; return the stored source."""
    added = await add_one(sources, actor, notebook, item)
    await sources.process_source.execute(added.id)
    return await stored(uow_factory, added.id)


async def stored(uow_factory: UowFactory, source_id: UUID) -> Source:
    """Read a source from the database."""
    async with uow_factory() as uow:
        found = await uow.sources.get(source_id)
    assert found is not None
    return found


async def stored_notebook(uow_factory: UowFactory, notebook_id: UUID) -> Notebook:
    """Read a notebook from the database."""
    async with uow_factory() as uow:
        found = await uow.notebooks.get(notebook_id)
    assert found is not None
    return found


async def passages_of(uow_factory: UowFactory, source_id: UUID) -> list[Passage]:
    """The stored passages of a source, by `seq`."""
    async with uow_factory() as uow:
        return await uow.passages.list_for_source(source_id, after_seq=0, limit=500)

"""Builders and readers shared by the chat tests."""

from collections.abc import AsyncIterator, Callable
from typing import Any

from app.modules.notebooks.application.views import StreamEvent
from app.modules.notebooks.domain.entities import (
    Notebook,
    NotebookMessage,
    Passage,
    Source,
)
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from tests.factories.notebooks import make_notebook, make_source

BIOLOGY = (
    "Photosynthesis turns light into chemical energy in plants.",
    "It happens in the chloroplasts, which contain chlorophyll.",
)
ANSWER = 'Light becomes energy [[S1:P1]].\n<followups>["Where?","Why?"]</followups>'
ANSWER_TEXT = "Light becomes energy ⟦1⟧."
CALVIN = "The Calvin cycle builds sugar from carbon dioxide."
FILLER = "Generic passage number {} about cells."
# Eight passages; the Calvin cycle is P5. With a small context cap it is retrieved.
BIG_NOTEBOOK = (
    *(FILLER.format(i) for i in range(1, 5)),
    CALVIN,
    *(FILLER.format(i) for i in range(6, 9)),
)

CoreFactory = Callable[..., NotebooksCore]


async def notebook_with_source(
    core: NotebooksCore,
    owner: Actor,
    *,
    texts: tuple[str, ...] = BIOLOGY,
    title: str = "Biology",
    **notebook_fields: Any,
) -> tuple[Notebook, Source]:
    """A notebook of the owner with one ready source."""
    notebook = await make_notebook(core.uow_factory, owner.user_id, **notebook_fields)
    source = await make_source(core.uow_factory, notebook, title=title, texts=texts)
    return notebook, source


async def thread(
    core: NotebooksCore, owner: Actor, notebook: Notebook
) -> list[NotebookMessage]:
    """The owner's stored messages in the notebook, oldest first."""
    async with core.uow_factory() as uow:
        return await uow.messages.list_tail(notebook.id, owner.user_id, 500)


async def passages_of(core: NotebooksCore, source: Source) -> list[Passage]:
    """The stored passages of a source, by `seq`."""
    async with core.uow_factory() as uow:
        return await uow.passages.list_for_source(source.id, after_seq=0, limit=500)


def sources_block(request: dict[str, Any]) -> str:
    """The `<sources>` block of a recorded model request."""
    content = request["messages"][0]["content"]
    return content if isinstance(content, str) else str(content[0]["text"])


def last_message(request: dict[str, Any]) -> str:
    """The text of the question message of a recorded model request."""
    return str(request["messages"][-1]["content"])


async def collect(events: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    """Read a whole stream."""
    return [event async for event in events]


def names(events: list[StreamEvent]) -> list[str]:
    """The event names in order."""
    return [event.name for event in events]


def streamed_text(events: list[StreamEvent]) -> str:
    """The text of all `delta` events."""
    return "".join(e.data["text"] for e in events if e.name == "delta")

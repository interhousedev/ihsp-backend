"""Entities of the notebooks module, built or stored through the SQL unit of work.

`new_*` builders only create entities. `make_*` helpers persist them in their own
transaction and return the stored entity::

    notebook = await make_notebook(uow_factory, student.user_id, pinned=True)
    source = await make_source(uow_factory, notebook, texts=("First.", "Second."))
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    Artifact,
    DraftPassage,
    MessageContent,
    Notebook,
    NotebookMessage,
    Source,
)
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    MessageRole,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.tokens import estimate_tokens
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.ids import new_id

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
DEFAULT_TEXT = "A passage of a source that talks about photosynthesis in plants."


def new_notebook_entity(owner_id: UUID | None = None, **fields: Any) -> Notebook:
    """A notebook that is not stored."""
    values: dict[str, Any] = {
        "id": new_id(),
        "owner_id": owner_id or new_id(),
        "title": "Biology",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(fields)
    return Notebook(**values)


def new_source_entity(notebook: Notebook, **fields: Any) -> Source:
    """A source of the notebook that is not stored (counters stay zero)."""
    values: dict[str, Any] = {
        "id": new_id(),
        "notebook_id": notebook.id,
        "owner_id": notebook.owner_id,
        "kind": SourceKind.TEXT,
        "title": "Source",
        "position": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(fields)
    return Source(**values)


def new_message_entity(
    notebook: Notebook, *, user_id: UUID | None = None, seq: int = 1, **fields: Any
) -> NotebookMessage:
    """A user message in the notebook's thread that is not stored."""
    values: dict[str, Any] = {
        "id": new_id(),
        "notebook_id": notebook.id,
        "user_id": user_id or notebook.owner_id,
        "seq": seq,
        "role": MessageRole.USER,
        "content": MessageContent(text="Question?"),
        "created_at": NOW,
    }
    values.update(fields)
    return NotebookMessage(**values)


def new_artifact_entity(notebook: Notebook, **fields: Any) -> Artifact:
    """A Studio output of the notebook that is not stored."""
    values: dict[str, Any] = {
        "id": new_id(),
        "notebook_id": notebook.id,
        "owner_id": notebook.owner_id,
        "kind": ArtifactKind.REPORT,
        "title": "Report",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(fields)
    return Artifact(**values)


def drafts_from_texts(texts: tuple[str, ...]) -> list[DraftPassage]:
    """One passage per text, `seq` 1..n; offsets in the texts joined by a blank line."""
    drafts: list[DraftPassage] = []
    offset = 0
    for seq, text in enumerate(texts, start=1):
        drafts.append(
            DraftPassage(
                seq=seq,
                text=text,
                char_start=offset,
                char_end=offset + len(text),
                token_estimate=max(estimate_tokens(len(text)), 1),
            )
        )
        offset += len(text) + 2
    return drafts


async def make_notebook(
    uow_factory: UowFactory, owner_id: UUID | None = None, **fields: Any
) -> Notebook:
    """Store a notebook of the owner; `fields` override the entity's fields."""
    notebook = new_notebook_entity(owner_id, **fields)
    async with uow_factory() as uow:
        await uow.notebooks.add(notebook)
        await uow.commit()
    return notebook


async def make_source(
    uow_factory: UowFactory,
    notebook: Notebook,
    *,
    kind: SourceKind = SourceKind.TEXT,
    texts: tuple[str, ...] = (DEFAULT_TEXT,),
    status: SourceStatus = SourceStatus.READY,
    **fields: Any,
) -> Source:
    """Store a source with one passage per text and counters that agree with them.

    The notebook's `source_count` and `char_count` follow (`notebook` is updated in
    place). Pass `texts=()` for a source that has no text yet (pending, failed).
    """
    body = "\n\n".join(texts)
    values: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "word_count": len(body.split()),
        "char_count": len(body),
        "token_estimate": estimate_tokens(len(body)),
        "passage_count": len(texts),
        "content_hash": (hashlib.sha256(body.encode()).hexdigest() if texts else None),
        "text_synced_at": NOW if texts else None,
    }
    values.update(fields)
    async with uow_factory() as uow:
        if "position" not in values:
            values["position"] = await uow.sources.next_position(notebook.id)
        if texts and "document_id" not in values:
            # Passages belong to a document: the same texts share one.
            document = await uow.documents.create(
                values["content_hash"],
                drafts_from_texts(texts),
                word_count=values["word_count"],
                char_count=values["char_count"],
                token_estimate=values["token_estimate"],
            )
            values["document_id"] = document.id
        source = new_source_entity(notebook, **values)
        await uow.sources.add(source)
        notebook.source_count += 1
        if source.usable:
            notebook.char_count += source.char_count
        await uow.notebooks.save(notebook)
        await uow.commit()
    return source


async def make_message(
    uow_factory: UowFactory,
    notebook: Notebook,
    *,
    role: MessageRole = MessageRole.USER,
    text: str = "Question?",
    user_id: UUID | None = None,
    **fields: Any,
) -> NotebookMessage:
    """Store the next message of the user's thread (`seq` follows the last one)."""
    owner = user_id or notebook.owner_id
    async with uow_factory() as uow:
        seq = (
            fields.pop("seq", None)
            or await uow.messages.last_seq(notebook.id, owner) + 1
        )
        fields.setdefault("content", MessageContent(text=text))
        message = new_message_entity(
            notebook, user_id=owner, seq=seq, role=role, **fields
        )
        await uow.messages.add(message)
        await uow.commit()
    return message


async def make_artifact(
    uow_factory: UowFactory,
    notebook: Notebook,
    kind: ArtifactKind = ArtifactKind.REPORT,
    status: ArtifactStatus = ArtifactStatus.READY,
    **fields: Any,
) -> Artifact:
    """Store a Studio output; a ready one gets content and a finish time."""
    values: dict[str, Any] = {"kind": kind, "status": status}
    if status is ArtifactStatus.READY:
        values["content"] = {"markdown": "# Report\n\nText."}
        values["started_at"] = NOW
        values["finished_at"] = NOW
    elif status is ArtifactStatus.GENERATING:
        values["started_at"] = NOW
    values.update(fields)
    artifact = new_artifact_entity(notebook, **values)
    async with uow_factory() as uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    return artifact

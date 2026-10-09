"""Builders for context packs, sources and passages used by the domain unit tests."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.modules.notebooks.domain.context import ContextMode, ContextPack
from app.modules.notebooks.domain.context_policy import build_pack
from app.modules.notebooks.domain.entities import Passage, Source, SourceGuide
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.tokens import estimate_tokens
from app.shared.ids import new_id

NOW = datetime(2026, 1, 1, tzinfo=UTC)
NOTEBOOK_ID = new_id()


def make_source(
    title: str = "Source",
    kind: SourceKind = SourceKind.FILE,
    *,
    guide: str | None = None,
    position: int = 0,
) -> Source:
    """Build a source with an optional guide summary."""
    source = Source(
        id=new_id(),
        notebook_id=NOTEBOOK_ID,
        owner_id=new_id(),
        kind=kind,
        title=title,
        position=position,
        created_at=NOW,
        updated_at=NOW,
    )
    if guide is not None:
        source.guide = SourceGuide(summary=guide)
    return source


def make_passage(
    source_id: UUID,
    seq: int,
    text: str = "",
    *,
    page: int | None = None,
    heading: str | None = None,
    tokens: int | None = None,
) -> Passage:
    """Build a stored passage; the token estimate defaults to the text size."""
    body = text or f"Passage {seq}"
    return Passage(
        id=new_id(),
        source_id=source_id,
        notebook_id=NOTEBOOK_ID,
        seq=seq,
        text=body,
        char_start=0,
        char_end=len(body),
        token_estimate=tokens if tokens is not None else estimate_tokens(len(body)),
        page=page,
        heading=heading,
    )


def make_pack(
    texts: Sequence[Sequence[str]],
    *,
    titles: Sequence[str] | None = None,
    mode: ContextMode = "full",
    guides: bool = False,
    guide_text: str | None = None,
) -> ContextPack:
    """Build a pack: one source per inner sequence, passages ``P1..Pn`` in order.

    Pages are the passage numbers, so ``S1:P2`` is on page 2.
    """
    sources: list[Source] = []
    passages: dict[UUID, list[Passage]] = {}
    for index, source_texts in enumerate(texts):
        title = titles[index] if titles else f"Source {index + 1}"
        source = make_source(title, position=index, guide=guide_text)
        sources.append(source)
        passages[source.id] = [
            make_passage(source.id, seq, text, page=seq)
            for seq, text in enumerate(source_texts, start=1)
        ]
    return build_pack(sources, passages, mode, guides=guides)

"""Pure parts of the context builder (§ 3.3.2): modes, packs, budgets, sampling.

The I/O side (reading passages, ranking) is in the application layer; everything here
is a function of its arguments.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.notebooks.domain.context import (
    ContextMode,
    ContextPack,
    PackPassage,
    PackSource,
    make_label,
)
from app.modules.notebooks.domain.entities import Passage, Source
from app.modules.notebooks.domain.tokens import estimate_tokens

SHORT_QUESTION_CHARS = 40
PREVIOUS_QUESTION_MAX_CHARS = 500
MIN_SOURCE_TOKENS = 2000


def build_pack(
    sources: Sequence[Source],
    passages_by_source: Mapping[UUID, Sequence[Passage]],
    mode: ContextMode,
    *,
    guides: bool = False,
) -> ContextPack:
    """Build the context pack of a request.

    Args:
        sources: The selected sources in order; source ``n`` is index + 1.
        passages_by_source: The passages that go into the context per source id.
        mode: How the passages were chosen.
        guides: Add the source guide summary to the sources that contribute passages
            (retrieval mode).

    Returns:
        The pack with labels ``S{n}:P{seq}``, the label map, the ``S1 -> id`` map and
        the title/kind of each source.
    """
    pack_sources: list[PackSource] = []
    labels: dict[str, PackPassage] = {}
    tokens = 0
    for n, source in enumerate(sources, start=1):
        chosen = sorted(passages_by_source.get(source.id, ()), key=lambda p: p.seq)
        packed = tuple(_pack_passage(n, source.id, p) for p in chosen)
        guide = _guide_of(source) if guides and packed else None
        pack_sources.append(
            PackSource(n, source.id, source.title, source.kind, packed, guide)
        )
        labels.update({p.label: p for p in packed})
        tokens += sum(p.token_estimate for p in packed)
        tokens += estimate_tokens(len(guide)) if guide else 0
    return ContextPack(
        sources=tuple(pack_sources),
        mode=mode,
        token_estimate=tokens,
        labels=labels,
        source_map={f"S{s.n}": s.source_id for s in pack_sources},
        titles={s.source_id: (s.title, s.kind) for s in pack_sources},
    )


def _pack_passage(n: int, source_id: UUID, passage: Passage) -> PackPassage:
    """Give a stored passage its label in this request."""
    return PackPassage(
        label=make_label(n, passage.seq),
        passage_id=passage.id,
        source_id=source_id,
        seq=passage.seq,
        text=passage.text,
        token_estimate=passage.token_estimate,
        page=passage.page,
        heading=passage.heading,
    )


def _guide_of(source: Source) -> str | None:
    """Return the guide summary of a source, if it has one."""
    return source.guide.summary if source.guide and source.guide.summary else None


def choose_chat_mode(selected_tokens: int, full_cap: int) -> ContextMode:
    """Chat sends everything up to `full_cap` tokens, else retrieves."""
    return "full" if selected_tokens <= full_cap else "retrieval"


def choose_studio_mode(selected_tokens: int, cap: int) -> ContextMode:
    """Studio sends everything up to `cap` tokens, else a stratified sample."""
    return "full" if selected_tokens <= cap else "sample"


def retrieval_query(question: str, previous_user_text: str | None) -> str:
    """Return the text to rank passages with.

    A short follow-up ("and why?") says little on its own, so the previous user
    message (at most 500 characters) is appended to it.
    """
    query = question.strip()
    previous = (previous_user_text or "").strip()
    if len(query) < SHORT_QUESTION_CHARS and previous:
        return f"{query} {previous[:PREVIOUS_QUESTION_MAX_CHARS]}".strip()
    return query


def expand_with_neighbours(
    by_source: Mapping[UUID, Sequence[Passage]],
    hits: Sequence[Passage],
    *,
    radius: int = 1,
    max_passages: int = 40,
    pinned: Sequence[Passage] = (),
) -> list[Passage]:
    """Add the neighbours (same source, ``seq`` within `radius`) of the hits.

    Anchored (`pinned`) passages are always kept, even above the cap. The rest fills
    the cap in this order: the hits (best first), the neighbours of the pinned
    passages, the neighbours of the hits (best first), so when over the cap the
    lowest-ranked hits go first.

    Args:
        by_source: All passages of the selected sources, in source order.
        hits: Ranked passages, best first.
        radius: How many passages on each side count as neighbours.
        max_passages: The cap, not counting pinned passages above it.
        pinned: Passages of the anchor.

    Returns:
        The passages ordered by source order of `by_source`, then ``seq``.
    """
    index = {
        source_id: {p.seq: p for p in passages}
        for source_id, passages in by_source.items()
    }
    chosen: dict[UUID, Passage] = {p.id: p for p in pinned}
    tiers = (
        list(hits),
        _neighbours_of(pinned, index, radius),
        _neighbours_of(hits, index, radius),
    )
    for tier in tiers:
        for passage in tier:
            if len(chosen) >= max_passages:
                break
            chosen.setdefault(passage.id, passage)
    order = {source_id: position for position, source_id in enumerate(by_source)}
    return sorted(
        chosen.values(),
        key=lambda p: (order.get(p.source_id, len(order)), p.seq),
    )


def _neighbours_of(
    passages: Sequence[Passage],
    index: Mapping[UUID, Mapping[int, Passage]],
    radius: int,
) -> list[Passage]:
    """List the neighbours of each passage: nearest first, previous before next."""
    found: list[Passage] = []
    for passage in passages:
        same_source = index.get(passage.source_id, {})
        for distance in range(1, radius + 1):
            for seq in (passage.seq - distance, passage.seq + distance):
                if seq in same_source:
                    found.append(same_source[seq])
    return found


def allocate_tokens(
    source_tokens: Mapping[UUID, int],
    budget: int,
    minimum: int = MIN_SOURCE_TOKENS,
) -> dict[UUID, int]:
    """Share a token budget between sources in proportion to their size.

    Each source gets at least `minimum` tokens, or its own size when smaller, and
    never more than its own size. The total exceeds the budget only because of the
    minimums.
    """
    sizes = {source_id: max(tokens, 0) for source_id, tokens in source_tokens.items()}
    total = sum(sizes.values())
    if total <= 0:
        return dict.fromkeys(sizes, 0)
    return {
        source_id: min(size, max(budget * size // total, min(minimum, size)))
        for source_id, size in sizes.items()
    }


def evenly_spaced(passages: Sequence[Passage], token_budget: int) -> list[Passage]:
    """Pick evenly spaced passages, in order, within a token budget.

    Always starts with the first passage. When even the first does not fit, the first
    passage that fits is returned; the result is empty only if none fits.
    """
    items = list(passages)
    size = len(items)
    total = sum(p.token_estimate for p in items)
    if size == 0 or token_budget <= 0:
        return []
    if total <= token_budget:
        return items
    count = max(1, min(size, token_budget * size // total))
    while count >= 1:
        picked = [items[(step * size) // count] for step in range(count)]
        if sum(p.token_estimate for p in picked) <= token_budget:
            return picked
        count -= 1
    return next(([p] for p in items if p.token_estimate <= token_budget), [])

"""Resolving `refs` labels ("S1:P4") of generated items against the context pack."""

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any, TypeVar

from app.modules.notebooks.domain.context import ContextPack, PackPassage
from app.modules.notebooks.domain.limits import SNIPPET_CHARS

MAX_REFS = 3
T = TypeVar("T")
# "S1:P4" and what models write instead: "[S1:P4]", "s1:p4", "S1 P04", "S1-P4", "S1P4".
_LOOSE_LABEL = re.compile(r"\[*\s*S\s*0*(\d+)\s*[:.\-]?\s*P\s*0*(\d+)\s*\]*", re.I)


def normalize_label(raw: object) -> str:
    """Return the canonical ``S{n}:P{m}`` form of a label, or the cleaned text."""
    text = str(raw).strip()
    match = _LOOSE_LABEL.fullmatch(text)
    if match is None:
        return text.strip("[]").replace(" ", "")
    return f"S{int(match.group(1))}:P{int(match.group(2))}"


def snippet_of(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Return the first `limit` characters of a passage on one line."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def valid_refs(refs: Iterable[str], pack: ContextPack) -> list[str]:
    """Keep the labels that exist in the pack (deduplicated, in order, at most 3)."""
    seen: dict[str, None] = {}
    for raw in refs:
        label = normalize_label(raw)
        if label in pack.labels:
            seen.setdefault(label)
    return list(seen)[:MAX_REFS]


def ref_entry(passage: PackPassage, pack: ContextPack) -> dict[str, Any]:
    """The `refs_index` value of one label (§ 3.4.0)."""
    title, kind = pack.titles[passage.source_id]
    return {
        "passage_id": str(passage.passage_id),
        "source_id": str(passage.source_id),
        "source_title": title,
        "source_kind": kind.value,
        "page": passage.page,
        "snippet": snippet_of(passage.text),
    }


def build_refs_index(
    all_refs: Iterable[Iterable[str]], pack: ContextPack
) -> dict[str, dict[str, Any]]:
    """Build `refs_index` for every label used by the items, resolved once."""
    index: dict[str, dict[str, Any]] = {}
    for refs in all_refs:
        for label in refs:
            if label not in index and label in pack.labels:
                index[label] = ref_entry(pack.labels[label], pack)
    return index


def keep_items_with_refs(
    items: Sequence[T], has_refs: Callable[[T], bool], requested: int
) -> list[T]:
    """Drop items whose refs are all invalid (§ 3.4.0).

    The items are kept as they are when dropping would leave fewer than half of the
    `requested` count (thin sources: a result with weak refs beats an empty one).
    """
    kept = [item for item in items if has_refs(item)]
    if len(kept) * 2 < requested:
        return list(items)
    return kept

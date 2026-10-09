"""The outline rules of a generated deck (§ 3.4.6), applied after each slide is repaired.

A deck opens with one title slide, may have one agenda right after it, closes with one
summary, repeats no slide and stays within two slides of the requested length. The
functions take and return lists of repaired slides (dicts with `layout`, `title`, …,
`refs`); they never invent content except the title slide, which only repeats the
deck's title.
"""

import json
from typing import Any, Final

from app.modules.notebooks.domain.artifacts.kind_support import norm_key

Slide = dict[str, Any]

TOLERANCE: Final = 2
# Layouts whose text is taken from the sources and must cite them.
CONTENT_LAYOUTS: Final = frozenset(
    {"bullets", "two_columns", "table", "quote", "summary"}
)
_NOT_CONTENT_KEYS: Final = frozenset({"notes", "refs", "visual_hint", "id"})


def _content_key(slide: Slide) -> str:
    """What makes two slides the same: layout and visible text (not notes or refs)."""
    visible = {k: v for k, v in slide.items() if k not in _NOT_CONTENT_KEYS}
    return norm_key(json.dumps(visible, ensure_ascii=False, sort_keys=True))


def drop_repeats(slides: list[Slide]) -> list[Slide]:
    """Keep the first of slides that show the same text."""
    seen: set[str] = set()
    kept: list[Slide] = []
    for slide in slides:
        key = _content_key(slide)
        if key not in seen:
            seen.add(key)
            kept.append(slide)
    return kept


def _relayout(slide: Slide, layout: str) -> Slide:
    return {**slide, "layout": layout}


def title_first(slides: list[Slide], deck_title: str) -> list[Slide]:
    """One title slide, first: moved there, or made from the deck title.

    Further title slides become section slides (they have the same fields).
    """
    first = next((s for s in slides if s["layout"] == "title"), None)
    rest = [
        _relayout(s, "section") if s["layout"] == "title" else s
        for s in slides
        if s is not first
    ]
    if first is None:
        first = {"layout": "title", "title": deck_title, "bullets": [], "notes": ""}
        first["refs"] = []
    return [first, *rest]


def agenda_second(slides: list[Slide]) -> list[Slide]:
    """At most one agenda, right after the title slide; others become bullets."""
    agenda = next((s for s in slides if s["layout"] == "agenda"), None)
    if agenda is None:
        return slides
    rest = [
        _relayout(s, "bullets") if s["layout"] == "agenda" else s
        for s in slides
        if s is not agenda
    ]
    return [*rest[:1], agenda, *rest[1:]]


def summary_last(slides: list[Slide]) -> list[Slide]:
    """At most one summary, the last slide; earlier ones become bullets."""
    summary = next((s for s in reversed(slides) if s["layout"] == "summary"), None)
    if summary is None:
        return slides
    rest = [
        _relayout(s, "bullets") if s["layout"] == "summary" else s
        for s in slides
        if s is not summary
    ]
    return [*rest, summary]


_FIXED: Final = frozenset({"title", "agenda", "summary"})


def _source_of(slide: Slide) -> str:
    """The source a slide is mostly about: the ``S{n}`` of its first ref."""
    refs = slide.get("refs") or []
    return str(refs[0]).split(":", 1)[0] if refs else ""


def _removable(slides: list[Slide]) -> int | None:
    """The slide to drop first when a deck is too long.

    Section slides go first, then slides without refs, then the last slide of the
    source that has the most slides, so every source keeps its slides as long as
    possible. The title, the agenda and the summary are never dropped.
    """
    candidates = [i for i, s in enumerate(slides) if s["layout"] not in _FIXED]
    if not candidates:
        return None
    for index in reversed(candidates):
        if slides[index]["layout"] == "section" or not slides[index].get("refs"):
            return index
    counts: dict[str, int] = {}
    for index in candidates:
        source = _source_of(slides[index])
        counts[source] = counts.get(source, 0) + 1
    busiest = max(counts.values())
    return next(
        index
        for index in reversed(candidates)
        if counts[_source_of(slides[index])] == busiest
    )


def trim(slides: list[Slide], target: int) -> list[Slide]:
    """At most `target + 2` slides, dropped in the order of `_removable`."""
    kept = list(slides)
    while len(kept) > target + TOLERANCE:
        index = _removable(kept)
        if index is None:
            break
        del kept[index]
    return kept


def shape_deck(slides: list[Slide], deck_title: str, target: int) -> list[Slide]:
    """Apply every outline rule, in order."""
    shaped = summary_last(agenda_second(title_first(drop_repeats(slides), deck_title)))
    return trim(shaped, target)


def uncited(slides: list[Slide]) -> list[int]:
    """1-based numbers of the content slides without refs."""
    return [
        number
        for number, slide in enumerate(slides, start=1)
        if slide["layout"] in CONTENT_LAYOUTS and not slide.get("refs")
    ]


def content_count(slides: list[Slide]) -> int:
    """How many slides carry content from the sources."""
    return sum(1 for slide in slides if slide["layout"] in CONTENT_LAYOUTS)

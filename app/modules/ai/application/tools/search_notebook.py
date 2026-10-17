"""Tool: search the passages of a notebook."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field

MAX_VARIANTS = 4


class SearchNotebookArgs(ToolArgs):
    """A notebook, a search phrase, its spelling variants and how many passages."""

    notebook_id: UUID
    query: str = Field(min_length=1, max_length=200)
    variants: list[str] = Field(default_factory=list, max_length=MAX_VARIANTS)
    limit: int = Field(default=8, ge=1, le=20)


class SearchNotebook(ReadTool[SearchNotebookArgs]):
    """Passages of a notebook's sources, best match first."""

    name = "search_notebook"
    description = (
        "Search passages of one notebook's sources (files, PDFs, pages) by meaning "
        "and words; returns source id and title, page and text. Give the topic as "
        "`query` and spellings of names in other scripts (Cyrillic, Latin, Uzbek) "
        "as `variants` in this one call. Cite the source title."
    )
    args_model = SearchNotebookArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(self, args: SearchNotebookArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the passages; an empty result still checks the notebook exists."""
        api = queries_of(self.bindings)
        ranked = [
            await api.search(ctx.actor.user_id, args.notebook_id, phrase, args.limit)
            for phrase in _phrases(args)
        ]
        rows = _interleaved(ranked, args.limit)
        if (
            not rows
            and await api.get_notebook(ctx.actor.user_id, args.notebook_id) is None
        ):
            raise ToolFailedError(support_details="notebook not found")
        return capped(rows)


def _phrases(args: SearchNotebookArgs) -> list[str]:
    """The query, then its distinct non-empty variants."""
    out: list[str] = []
    for phrase in (args.query, *args.variants):
        text = phrase.strip()[:200]
        if text and text.casefold() not in {p.casefold() for p in out}:
            out.append(text)
    return out


def _interleaved(
    ranked: list[list[dict[str, Any]]], limit: int
) -> list[dict[str, Any]]:
    """At most `limit` distinct passages, taking each phrase's next best in turn."""
    rows: list[dict[str, Any]] = []
    found: set[tuple[Any, Any]] = set()
    for rank in range(max((len(r) for r in ranked), default=0)):
        for hits in ranked:
            if rank >= len(hits):
                continue
            key = (hits[rank].get("source_id"), hits[rank].get("seq"))
            if key not in found:
                found.add(key)
                rows.append(hits[rank])
    return rows[:limit]

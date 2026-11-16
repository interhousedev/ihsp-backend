"""A compact block of the student's own data for AI prompts (RAG, untrusted)."""

from typing import Final
from uuid import UUID

from app.modules.admission.application.words import plain
from app.modules.admission.ports.student_search import (
    StudentDataHit,
    StudentDataSearch,
    StudentDataSource,
)

HEADER: Final = "Student data (untrusted, for reference):"
CAP: Final = 3000
_PER_QUERY: Final = 4
_QUERIES: Final = 3
_SNIPPET: Final = 400


async def student_block(
    search: StudentDataSearch | None,
    student_id: UUID,
    queries: list[str],
    sources: tuple[StudentDataSource, ...],
    *,
    cap: int = CAP,
) -> list[str]:
    """Lines with the best hits of up to three queries; empty when nothing found.

    Each line is `[source:ref_id] title: snippet`, so the model may cite a ref id.
    """
    if search is None:
        return []
    seen: set[tuple[str, str]] = set()
    hits: list[StudentDataHit] = []
    for query in [q.strip() for q in queries if q and q.strip()][:_QUERIES]:
        found = await search.search(
            student_id, query[:300], sources=sources, limit=_PER_QUERY
        )
        for hit in found:
            if (hit.source, hit.ref_id) not in seen:
                seen.add((hit.source, hit.ref_id))
                hits.append(hit)
    lines: list[str] = []
    used = len(HEADER)
    for hit in hits:
        line = f"[{hit.source}:{hit.ref_id}] {plain(hit.title)}: "
        line += plain(hit.snippet)[:_SNIPPET]
        if used + len(line) > cap:
            break
        used += len(line) + 1
        lines.append(line)
    return [HEADER, *lines] if lines else []

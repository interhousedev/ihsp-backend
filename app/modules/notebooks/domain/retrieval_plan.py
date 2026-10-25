"""Rules of the cheap retrieval helpers: complex questions, follow-ups, digests.

The notebook chat may ask a small model whether the retrieved passages answer a
question (multi-hop retrieval), whether a question is several questions in one
(query decomposition), and whether a Studio output says only what its sources say
(faithfulness). This file keeps their schemas and the plain rules around them.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any, Final

from app.modules.notebooks.domain.entities import Passage

COMPLEX_MIN_CHARS: Final = 40  # shorter questions are never split
LONG_QUESTION_CHARS: Final = 160  # this long is complex whatever its words
QUERY_MAX_CHARS: Final = 200
DIGEST_PASSAGE_CHARS: Final = 280
DIGEST_MAX_PASSAGES: Final = 24

# Words that join two asks in one question (en, ru, uz).
_JOINERS: Final = re.compile(
    r"\b(and|also|compare|versus|vs|difference|"
    r"и|а также|сравни\w*|разниц\w*|отлич\w*|"
    r"va|hamda|solishtir\w*|farq\w*)\b",
    re.IGNORECASE,
)

SUFFICIENCY_SCHEMA_NAME: Final = "nb_retrieval_plan"
DECOMPOSE_SCHEMA_NAME: Final = "nb_query_decompose"
FAITHFULNESS_SCHEMA_NAME: Final = "nb_faithfulness"


def _strings_schema(flag: str, items: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            flag: {"type": "boolean"},
            items: {"type": "array", "items": {"type": "string"}},
        },
        "required": [flag, items],
        "additionalProperties": False,
    }


SUFFICIENCY_SCHEMA: Final = _strings_schema("sufficient", "queries")
DECOMPOSE_SCHEMA: Final = _strings_schema("complex", "parts")
FAITHFULNESS_SCHEMA: Final = _strings_schema("faithful", "unsupported")


def looks_complex(question: str) -> bool:
    """True when a question may hold several asks (worth a classification call)."""
    text = question.strip()
    if len(text) < COMPLEX_MIN_CHARS:
        return False
    if len(text) >= LONG_QUESTION_CHARS or text.count("?") > 1:
        return True
    return _JOINERS.search(text) is not None


def clean_queries(raw: object, limit: int, *, seen: Iterable[str] = ()) -> list[str]:
    """The queries: strings, trimmed, distinct, unseen, at most `limit`."""
    if not isinstance(raw, list) or limit <= 0:
        return []
    known = {q.casefold() for q in seen}
    queries: list[str] = []
    for item in raw:
        text = " ".join(str(item).split())[:QUERY_MAX_CHARS] if item else ""
        if text and text.casefold() not in known:
            known.add(text.casefold())
            queries.append(text)
        if len(queries) >= limit:
            break
    return queries


def new_passages(known: Sequence[Passage], found: Sequence[Passage]) -> list[Passage]:
    """The passages of `found` whose ids are not in `known`, in order, once each."""
    ids = {p.id for p in known}
    fresh: list[Passage] = []
    for passage in found:
        if passage.id not in ids:
            ids.add(passage.id)
            fresh.append(passage)
    return fresh


def interleave(groups: Sequence[Sequence[Passage]], limit: int) -> list[Passage]:
    """Round-robin over the groups (best first in each), no repeats, at most `limit`."""
    merged: list[Passage] = []
    longest = max((len(g) for g in groups), default=0)
    for rank in range(longest):
        for group in groups:
            if rank < len(group) and len(merged) < limit:
                merged.extend(new_passages(merged, [group[rank]]))
    return merged


def digest(passages: Sequence[Passage]) -> str:
    """A short numbered view of the passages for a small model."""
    lines = [
        f"[{n}] {' '.join(p.text.split())[:DIGEST_PASSAGE_CHARS]}"
        for n, p in enumerate(passages[:DIGEST_MAX_PASSAGES], start=1)
    ]
    return "\n".join(lines) or "(no passages)"


SUFFICIENCY_SYSTEM: Final = (
    "You check whether study passages contain what is needed to answer a student's "
    "question. Answer `sufficient: true` when they do. Otherwise list in `queries` "
    "short search queries (in the question's language) for the missing facts only. "
    "Never answer the question."
)
DECOMPOSE_SYSTEM: Final = (
    "You split a student's question into independent sub-questions. When it asks "
    "one thing, answer `complex: false` and no parts. Otherwise give each "
    "self-contained sub-question in `parts`, in the question's language."
)
FAITHFULNESS_SYSTEM: Final = (
    "You check a generated study material against its sources. `faithful` is "
    "false only when the material states facts that the sources contradict or do "
    "not contain; list those claims briefly in `unsupported`. Style, structure and "
    "general phrasing are not claims."
)


def sufficiency_message(question: str, passages: Sequence[Passage]) -> str:
    """The user message of the sufficiency check."""
    return (
        f"<question>{question}</question>\n<passages>\n{digest(passages)}\n</passages>"
    )


def decompose_message(question: str, max_parts: int) -> str:
    """The user message of the decomposition."""
    return f"At most {max_parts} parts.\n<question>{question}</question>"


def faithfulness_message(material: str, sources: str) -> str:
    """The user message of the faithfulness check."""
    return f"{sources}\n<material>\n{material}\n</material>"

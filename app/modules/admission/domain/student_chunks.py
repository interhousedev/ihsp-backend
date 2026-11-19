"""Searchable pieces of one student's data and the links back into the app."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

from app.modules.admission.ports.student_search import StudentDataSource

CHUNK_CHARS: Final = 1200
"""A body longer than this is split on whitespace into several chunks."""
MAX_CHUNKS_PER_REF: Final = 6
MAX_VECTOR_DISTANCE: Final = 0.6
"""Cosine distance above which a chunk is not a vector hit (0 is identical)."""
SNIPPET_CHARS: Final = 240

_PATHS: Final[dict[str, str]] = {
    "profile": "/settings/?tab=profile",
    "item": "/activities",
    "task": "/tasks",
    "test_score": "/tests",
    "document": "/documents",
    "career": "/career",
    "list": "/chooser/list",
    "opportunity": "/opportunities",
    "course": "/courses",
    "grade": "/courses",
}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One indexed piece: `ref_id` names the row it came from, `seq` the part."""

    source: StudentDataSource
    ref_id: str
    title: str
    body: str
    seq: int = 0

    @property
    def content_hash(self) -> str:
        """sha256 of the embedded text (the key in `vectors.embeddings`)."""
        return hashlib.sha256(self.embed_text.encode()).hexdigest()

    @property
    def embed_text(self) -> str:
        """The text that is embedded and searched by words."""
        return f"{self.title}\n{self.body}".strip()


def url_path(source: str, ref_id: str) -> str:
    """The admission web page that shows the row."""
    if source == "essay":
        return f"/essays/{ref_id}"
    return _PATHS.get(source, "/")


def snippet(body: str) -> str:
    """A short single-line extract of a chunk body."""
    flat = " ".join(body.split())
    if len(flat) <= SNIPPET_CHARS:
        return flat
    return flat[: SNIPPET_CHARS - 1].rstrip() + "…"


def split_body(body: str) -> list[str]:
    """Parts of at most `CHUNK_CHARS`, cut at whitespace; blank input gives none."""
    words = body.split()
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for word in words:
        if size and size + len(word) + 1 > CHUNK_CHARS:
            parts.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += len(word) + 1
    if current:
        parts.append(" ".join(current))
    return parts[:MAX_CHUNKS_PER_REF]


def make_chunks(
    source: StudentDataSource, ref_id: str, title: str, body: str
) -> list[Chunk]:
    """The chunks of one row; a row with neither title nor body has none."""
    parts = split_body(body) or ([""] if title.strip() else [])
    return [
        Chunk(source, ref_id, title.strip(), part, i) for i, part in enumerate(parts)
    ]


def query_tokens(query: str) -> list[str]:
    """Distinct lowercase words of a query (letters and digits, any script)."""
    return list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))[:12]


def fuse(
    rankings: list[list[tuple[str, str]]], *, k: int = 60
) -> list[tuple[tuple[str, str], float]]:
    """Reciprocal rank fusion of ranked `(source, ref_id)` lists, best first."""
    score: dict[tuple[str, str], float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking)):
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))

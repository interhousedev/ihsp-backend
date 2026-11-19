"""Public essays of admitted students that a review compares a draft with."""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import ExemplarInvalidError
from app.modules.admission.domain.urls import is_https_url

ExemplarKind = Literal[
    "personal_statement", "supplement", "why_us", "activity", "other"
]
ExemplarStatus = Literal["draft", "published", "archived"]

EXEMPLAR_KINDS: Final[tuple[ExemplarKind, ...]] = (
    "personal_statement",
    "supplement",
    "why_us",
    "activity",
    "other",
)
EXEMPLAR_STATUSES: Final[tuple[ExemplarStatus, ...]] = (
    "draft",
    "published",
    "archived",
)

EXCERPT_WORDS: Final = 80
MAX_IMPORT: Final = 50
MAX_BODY_LEN: Final = 20000
MAX_PROMPT_LEN: Final = 4000
MAX_TITLE_LEN: Final = 200
MAX_URL_LEN: Final = 500
MAX_TAGS: Final = 12
MAX_TAG_LEN: Final = 40


@dataclass(frozen=True, slots=True)
class Exemplar:
    """One published essay with the source it was taken from."""

    id: UUID
    institution_id: UUID | None
    school_name: str
    year: int | None
    kind: ExemplarKind
    prompt: str
    title: str
    body: str
    word_count: int
    source_url: str
    source_name: str
    tags: tuple[str, ...]
    notes: str
    status: ExemplarStatus
    language: str
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    lock_version: int


@dataclass(frozen=True, slots=True)
class ExemplarMatch:
    """An exemplar close to a draft; `similarity` is between 0 and 1."""

    exemplar: Exemplar
    similarity: float


_WORD: Final = re.compile(r"[^\W\d_]+(?:['ʻʼ’][^\W\d_]+)*", re.UNICODE)
INSTITUTION_BOOST: Final = 0.15
_FAMILIES: Final[dict[str, frozenset[str]]] = {
    "personal_statement": frozenset({"personal_statement"}),
    "supplemental": frozenset({"supplement", "why_us"}),
}


def invalid(field: str, reason: str) -> ExemplarInvalidError:
    """The error of a field that breaks a rule."""
    return ExemplarInvalidError(params={"field": field, "reason": reason})


def count_words(text: str) -> int:
    """Number of whitespace separated words."""
    return len(text.split())


def excerpt(body: str, words: int = EXCERPT_WORDS) -> str:
    """The first `words` words; a cut text ends with an ellipsis on the last word."""
    parts = body.split()
    if len(parts) <= words:
        return " ".join(parts)
    return " ".join(parts[:words]) + "…"


def check_text(field: str, value: str, limit: int, *, required: bool = True) -> str:
    """Trim the text and check its length; empty is refused when required."""
    out = value.strip()
    if required and not out:
        raise invalid(field, "empty")
    if len(out) > limit:
        raise invalid(field, f"too_long:{limit}")
    return out


def check_url(value: str) -> str:
    """A plain https address of at most MAX_URL_LEN characters."""
    out = value.strip()
    if len(out) > MAX_URL_LEN or not is_https_url(out):
        raise invalid("source_url", "https_required")
    return out


def check_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """Trimmed, lower-cased, de-duplicated tags within the frozen limits."""
    out: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag:
            raise invalid("tags", "empty")
        if len(tag) > MAX_TAG_LEN:
            raise invalid("tags", f"tag_too_long:{MAX_TAG_LEN}")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise invalid("tags", f"too_many:{MAX_TAGS}")
    return tuple(out)


def kind_rank(essay_kind: str, exemplar_kind: str) -> int:
    """2 = preferred kind, 1 = usable, 0 = not comparable."""
    if essay_kind == "other":
        return 2 if exemplar_kind == "other" else 1
    family = _FAMILIES.get(essay_kind)
    if family is None:
        return 2 if exemplar_kind == essay_kind else 0
    return 2 if exemplar_kind in family else 0


def tokens(text: str) -> list[str]:
    """Lower-cased words of the text."""
    return [m.group(0).lower() for m in _WORD.finditer(text)]


def idf(docs: Sequence[Sequence[str]]) -> dict[str, float]:
    """Smoothed inverse document frequency of every term of the corpus."""
    n = len(docs)
    freq: Counter[str] = Counter()
    for doc in docs:
        freq.update(set(doc))
    return {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in freq.items()}


def tfidf(doc: Sequence[str], weights: dict[str, float]) -> dict[str, float]:
    """L2-normalised TF-IDF vector; terms outside the corpus are dropped."""
    vec = {t: c * weights[t] for t, c in Counter(doc).items() if t in weights}
    norm = math.sqrt(sum(v * v for v in vec.values()))
    return {t: v / norm for t, v in vec.items()} if norm else {}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Dot product of two normalised vectors, between 0 and 1."""
    if len(a) > len(b):
        a, b = b, a
    return min(1.0, sum(v * b.get(t, 0.0) for t, v in a.items()))


def rank_key(
    essay_kind: str, institution_id: UUID | None, item: Exemplar, similarity: float
) -> tuple[int, float]:
    """Sort key, higher is better: kind first, then boosted similarity."""
    boost = (
        INSTITUTION_BOOST
        if institution_id is not None and item.institution_id == institution_id
        else 0.0
    )
    return kind_rank(essay_kind, item.kind), similarity + boost

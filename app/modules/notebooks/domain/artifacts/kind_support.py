"""Helpers shared by the quiz, data table, slides and infographic kinds.

Text trimming, option parsing, per-item validation of the model's JSON and the
resolution of ref labels against a set of known labels.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any, Literal, TypeVar
from uuid import UUID

from app.modules.notebooks.domain.artifacts.refs import normalize_label
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

MAX_REF_LABELS = 3
MAX_RAW_ITEMS = 200  # never look at more items than this in one model output
_SPACES = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[\W_]+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_LABEL = re.compile(r"S\d+:P\d+")


class CommonOptions(BaseModel):
    """Options of every kind: the output language and a subset of the sources."""

    language: Literal["uz", "ru", "en"] | None = None
    source_ids: list[UUID] | None = None


def parse_options(model: type[M], raw: dict[str, Any]) -> M:
    """Validate raw request options; pydantic errors become `InvalidOptionsError`."""
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        details = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(
                include_url=False, include_context=False, include_input=False
            )
        ]
        raise InvalidOptionsError(
            params={"details": details}, support_details="; ".join(details)[:500]
        ) from exc


def expect_options(options: BaseModel, model: type[M]) -> M:
    """Narrow the protocol's `BaseModel` to the kind's own options class."""
    if not isinstance(options, model):
        raise TypeError(f"expected {model.__name__}, got {type(options).__name__}")
    return options


def dump_options(options: BaseModel) -> dict[str, Any]:
    """Options as stored and echoed back: defaults filled, JSON-safe, no nulls."""
    return options.model_dump(mode="json", exclude_none=True)


def clean_text(value: object) -> str:
    """Collapse all whitespace; anything that is not a string becomes ``""``."""
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", value).strip()


def clip_chars(text: str, limit: int) -> str:
    """Cut to `limit` characters, ending with an ellipsis when something was cut."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def clip_words(text: str, limit: int) -> str:
    """Keep the first `limit` words, ending with an ellipsis when words were cut."""
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(",;:.-") + "…"


def fit_text(
    value: object, *, words: int | None = None, chars: int | None = None
) -> str:
    """Clean a text and apply the word and character caps (words first)."""
    text = clean_text(value)
    if words is not None:
        text = clip_words(text, words)
    if chars is not None:
        text = clip_chars(text, chars)
    return text


def strip_urls(text: str) -> str:
    """Remove ``http(s)://`` and ``www.`` addresses; visual hints are text only."""
    return clean_text(_URL.sub("", text))


def norm_key(text: str) -> str:
    """Normalise a text for duplicate detection (case, punctuation, spaces)."""
    return _NOT_WORD.sub(" ", text.casefold()).strip()


def require_list(data: dict[str, Any], key: str) -> list[Any]:
    """Return ``data[key]`` or fail the document when it is not a list."""
    value = data.get(key)
    if not isinstance(value, list):
        raise OutputInvalidError([f"`{key}` must be a list"])
    return value[:MAX_RAW_ITEMS]


def validate_numbered(
    model: type[M], raw_items: Iterable[Any], problems: list[str], label: str
) -> list[tuple[int, M]]:
    """Validate each item on its own; broken ones are dropped and reported.

    Returns ``(number, item)`` pairs, the number being the 1-based position in the
    model's list. Only the first error of an item is reported, as
    ``label N: path: message``; the message never echoes the model's text.
    """
    valid: list[tuple[int, M]] = []
    for number, raw in enumerate(raw_items, start=1):
        try:
            valid.append((number, model.model_validate(raw)))
        except ValidationError as exc:
            error = exc.errors(
                include_url=False, include_context=False, include_input=False
            )[0]
            where = ".".join(str(part) for part in error["loc"])
            problems.append(f"{label} {number}: {where}: {error['msg']}")
    return valid


def validate_items(
    model: type[M], raw_items: Iterable[Any], problems: list[str], label: str
) -> list[M]:
    """Like `validate_numbered`, without the numbers."""
    return [item for _, item in validate_numbered(model, raw_items, problems, label)]


def document_title(data: dict[str, Any], pack: ContextPack, fallback: str) -> str:
    """The model's title, else the first source title, else a plain word."""
    title = fit_text(data.get("title"), chars=ARTIFACT_TITLE_MAX_CHARS)
    if title:
        return title
    if pack.sources:
        return fit_text(pack.sources[0].title, chars=ARTIFACT_TITLE_MAX_CHARS)
    return fallback


def clean_label(raw: object) -> str:
    """Normalise a ref label the way `valid_refs` does."""
    return normalize_label(raw)


def refs_among(refs: Sequence[object] | None, labels: set[str] | None) -> list[str]:
    """Keep the labels found in `labels` (unique, in order, at most three).

    With ``labels=None`` the set is unknown and only well-formed labels
    (``S1:P4``) are kept.
    """
    seen: dict[str, None] = {}
    for raw in refs or []:
        label = clean_label(raw)
        known = label in labels if labels is not None else _LABEL.fullmatch(label)
        if known:
            seen.setdefault(label)
    return list(seen)[:MAX_REF_LABELS]

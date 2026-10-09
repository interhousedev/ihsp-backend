"""Topics of a subject: a tree with names in three languages (LIB-4). Pure rules."""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.taxonomy_errors import (
    NameRequiredError,
    SlugInvalidError,
    TopicParentInvalidError,
)
from app.shared.text import slugify

LANGUAGES = ("uz", "ru", "en")
SLUG_MAX = 80
SLUG_FALLBACK = "topic"
YEAR_OF_STUDY_MAX = 4
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Which language gives the readable slug first.
_SLUG_LANGUAGES = ("en", "ru", "uz")


@dataclass(slots=True)
class Topic:
    """A topic of a subject; `parent_id` None makes it a root."""

    id: UUID
    subject_id: UUID
    parent_id: UUID | None
    name: dict[str, str]
    slug: str
    position: int
    year_of_study: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TopicNode:
    """A topic with its children, ordered by position."""

    topic: Topic
    children: tuple["TopicNode", ...] = ()


# - - - Names and slugs - - -


def clean_names(names: Mapping[str, str]) -> dict[str, str]:
    """All three languages with spaces collapsed; at least one must be filled."""
    cleaned = {lang: " ".join(names.get(lang, "").split()) for lang in LANGUAGES}
    if not any(cleaned.values()):
        raise NameRequiredError()
    return cleaned


def clean_optional_names(names: Mapping[str, str] | None) -> dict[str, str]:
    """Like `clean_names`, but nothing at all gives an empty dict."""
    if names is None:
        return {}
    cleaned = {lang: " ".join(names.get(lang, "").split()) for lang in LANGUAGES}
    return cleaned if any(cleaned.values()) else {}


def slug_from_names(names: Mapping[str, str]) -> str:
    """The slug of the first language (English, Russian, Uzbek) that has letters."""
    for language in _SLUG_LANGUAGES:
        slug = slugify(names.get(language, ""))[:SLUG_MAX].strip("-")
        if slug:
            return slug
    return SLUG_FALLBACK


def unique_slug(base: str, taken: Collection[str]) -> str:
    """`base`, or `base-2`, `base-3`, ... until it is not in `taken`."""
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = f"{base[: SLUG_MAX - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1


def validate_slug(slug: str) -> str:
    """The slug itself when it is lowercase Latin words joined by hyphens."""
    if len(slug) > SLUG_MAX or not _SLUG_PATTERN.match(slug):
        raise SlugInvalidError(params={"slug": slug[: SLUG_MAX + 1]})
    return slug


# - - - Tree - - -


def build_tree(topics: Sequence[Topic]) -> list[TopicNode]:
    """Roots with their children; siblings by position, then slug.

    A topic whose parent is not in `topics` is shown as a root.
    """
    known = {topic.id for topic in topics}
    by_parent: dict[UUID | None, list[Topic]] = {}
    for topic in topics:
        parent = topic.parent_id if topic.parent_id in known else None
        by_parent.setdefault(parent, []).append(topic)

    def nodes(parent: UUID | None) -> tuple[TopicNode, ...]:
        siblings = sorted(
            by_parent.get(parent, []),
            key=lambda t: (t.subject_id, t.position, t.slug),
        )
        return tuple(TopicNode(t, nodes(t.id)) for t in siblings)

    return list(nodes(None))


def descendant_ids(topics: Sequence[Topic], topic_id: UUID) -> set[UUID]:
    """Ids of everything below the topic (not the topic itself)."""
    children: dict[UUID, list[UUID]] = {}
    for topic in topics:
        if topic.parent_id is not None:
            children.setdefault(topic.parent_id, []).append(topic.id)
    found: set[UUID] = set()
    stack = [topic_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def check_parent(
    topics: Sequence[Topic],
    *,
    subject_id: UUID,
    parent_id: UUID,
    topic_id: UUID | None = None,
) -> None:
    """The parent exists in the subject and the move keeps the tree acyclic.

    `topics` are the topics of the subject; `topic_id` is the topic being moved.
    """
    parent = next((t for t in topics if t.id == parent_id), None)
    if parent is None or parent.subject_id != subject_id:
        raise TopicParentInvalidError(params={"parent_id": str(parent_id)})
    if topic_id is not None and (
        parent_id == topic_id or parent_id in descendant_ids(topics, topic_id)
    ):
        raise TopicParentInvalidError(params={"parent_id": str(parent_id)})

"""Bot posts: a tree of rich-text pages shown in the Telegram bot."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.posts.domain.errors import InvalidPostError
from app.modules.posts.domain.sanitize import sanitize_telegram_html

LANGUAGES: Final = ("uz", "ru", "en")
BODY_MAX: Final = 4000
TITLE_MAX: Final = 128
LABEL_MAX: Final = 64
URL_MAX: Final = 2048
BUTTONS_MAX: Final = 8
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class Audience(StrEnum):
    """Who sees a post."""

    GUEST = "guest"
    STUDENT = "student"
    BOTH = "both"


class Viewer(StrEnum):
    """Who looks at the bot: a guest (parents, applicants) or a student/staff."""

    GUEST = "guest"
    STUDENT = "student"


def localized(value: Mapping[str, str], *, limit: int, what: str) -> dict[str, str]:
    """Keep uz/ru/en values (trimmed); refuse other keys, empty sets, long values."""
    unknown = set(value) - set(LANGUAGES)
    if unknown:
        raise InvalidPostError(params={"field": what, "reason": "language"})
    out = {lang: text.strip() for lang, text in value.items() if text and text.strip()}
    if not out:
        raise InvalidPostError(params={"field": what, "reason": "empty"})
    if any(len(text) > limit for text in out.values()):
        raise InvalidPostError(params={"field": what, "reason": "too-long"})
    return out


def body_texts(value: Mapping[str, str]) -> dict[str, str]:
    """Sanitized bodies (Telegram HTML subset); each at most BODY_MAX characters."""
    unknown = set(value) - set(LANGUAGES)
    if unknown:
        raise InvalidPostError(params={"field": "body", "reason": "language"})
    out: dict[str, str] = {}
    for lang, text in value.items():
        clean = sanitize_telegram_html(text or "").strip()
        if len(clean) > BODY_MAX:
            raise InvalidPostError(params={"field": "body", "reason": "too-long"})
        if clean:
            out[lang] = clean
    return out


def https_url(url: str) -> str:
    """An absolute https URL with a host."""
    url = url.strip()
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or len(url) > URL_MAX
        or any(ch.isspace() for ch in url)
    ):
        raise InvalidPostError(params={"field": "buttons", "reason": "url"})
    return url


@dataclass(frozen=True, slots=True)
class UrlButton:
    """An extra link button under a post."""

    label: dict[str, str]
    url: str

    @classmethod
    def of(cls, label: Mapping[str, str], url: str) -> "UrlButton":
        """Validate the label and the URL."""
        return cls(localized(label, limit=LABEL_MAX, what="buttons"), https_url(url))


def buttons_of(items: Iterable[UrlButton]) -> tuple[UrlButton, ...]:
    """At most BUTTONS_MAX buttons."""
    out = tuple(items)
    if len(out) > BUTTONS_MAX:
        raise InvalidPostError(params={"field": "buttons", "reason": "too-many"})
    return out


def check_slug(slug: str) -> str:
    """Lower-case letters, digits and dashes, at most 64 characters."""
    if not SLUG.match(slug):
        raise InvalidPostError(params={"field": "slug", "reason": "format"})
    return slug


@dataclass(frozen=True, slots=True)
class Post:
    """One node of the tree; exactly one post is the root (main menu)."""

    id: UUID
    parent_id: UUID | None
    slug: str
    title: dict[str, str]
    body: dict[str, str] = field(default_factory=dict)
    audience: Audience = Audience.BOTH
    sort_order: int = 0
    published: bool = True
    is_root: bool = False
    buttons: tuple[UrlButton, ...] = ()

    def visible_to(self, viewer: Viewer) -> bool:
        """Published and meant for the viewer (the root is always visible)."""
        if self.is_root:
            return True
        if not self.published:
            return False
        return self.audience == Audience.BOTH or self.audience.value == viewer.value

    def with_changes(self, **changes: object) -> "Post":
        """A copy with some fields replaced."""
        return replace(self, **changes)  # type: ignore[arg-type]


def pick(texts: Mapping[str, str], locale: str) -> str:
    """The text in the locale, else en, ru, uz, else empty."""
    for lang in (locale, "en", "ru", "uz"):
        if texts.get(lang):
            return texts[lang]
    return ""


class Tree:
    """The posts in memory, indexed by id and parent (posts are few)."""

    def __init__(self, posts: Iterable[Post]) -> None:
        """Index the posts."""
        self.by_id: dict[UUID, Post] = {post.id: post for post in posts}

    @property
    def root(self) -> Post | None:
        """The root post, if any."""
        return next((p for p in self.by_id.values() if p.is_root), None)

    def children(self, parent_id: UUID) -> list[Post]:
        """Children ordered by sort_order then slug."""
        found = [p for p in self.by_id.values() if p.parent_id == parent_id]
        return sorted(found, key=lambda p: (p.sort_order, p.slug))

    def descendants(self, post_id: UUID) -> set[UUID]:
        """Every post below `post_id` (not itself)."""
        out: set[UUID] = set()
        stack = [post_id]
        while stack:
            for child in self.children(stack.pop()):
                if child.id not in out:
                    out.add(child.id)
                    stack.append(child.id)
        return out

    def path_visible(self, post_id: UUID, viewer: Viewer) -> bool:
        """The post and all its ancestors are visible to the viewer."""
        seen: set[UUID] = set()
        current = self.by_id.get(post_id)
        while current is not None and current.id not in seen:
            if not current.visible_to(viewer):
                return False
            seen.add(current.id)
            if current.parent_id is None:
                return current.is_root
            current = self.by_id.get(current.parent_id)
        return False

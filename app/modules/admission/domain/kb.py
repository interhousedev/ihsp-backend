"""The admission FAQ knowledge base: short articles counselors keep up to date."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.entitlement import AdmissionActor
from app.modules.admission.domain.errors import CharLimitError
from app.shared.actor import Role

ArticleStatus = Literal["draft", "published"]
STATUSES: Final[tuple[ArticleStatus, ...]] = ("draft", "published")
KB_LOCALES: Final = ("uz", "ru", "en")
TITLE_MAX: Final = 200
BODY_MAX: Final = 20_000
TAG_MAX: Final = 40
TAGS_MAX: Final = 10
# Who edits the FAQ: administrators, counselors and mentors (the staff helpers).
EDITOR_ROLES: Final = frozenset({Role.ADMIN, Role.COUNSELOR, Role.MENTOR})


@dataclass(slots=True)
class Article:
    """One FAQ article in one language."""

    id: UUID
    title: str
    body: str  # Markdown
    locale: str
    status: ArticleStatus
    author_id: UUID | None
    created_at: datetime
    updated_at: datetime
    tags: list[str] = field(default_factory=list)


def can_edit_kb(admission: AdmissionActor, roles: frozenset[Role]) -> bool:
    """Return whether the caller may create, edit, delete and see drafts."""
    return bool((roles | admission.staff_roles) & EDITOR_ROLES)


def can_read_kb(admission: AdmissionActor) -> bool:
    """Return whether the caller may read published articles."""
    return admission.may_enter


def clean_tags(tags: list[str]) -> list[str]:
    """Lower-case, trimmed, unique tags in their first order."""
    out: list[str] = []
    for raw in tags:
        tag = " ".join(raw.split()).lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def check_article(title: str, body: str, tags: list[str]) -> None:
    """Raise CharLimitError when a field is empty or too long."""
    for name, value, limit in (("title", title, TITLE_MAX), ("body", body, BODY_MAX)):
        if not value.strip() or len(value) > limit:
            raise CharLimitError(params={"field": name, "limit": limit})
    if len(tags) > TAGS_MAX or any(len(t) > TAG_MAX for t in tags):
        raise CharLimitError(params={"field": "tags", "limit": TAG_MAX})


def snippet(body: str, limit: int = 280) -> str:
    """The first characters of the body as one line."""
    text = " ".join(body.replace("#", " ").replace("*", " ").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

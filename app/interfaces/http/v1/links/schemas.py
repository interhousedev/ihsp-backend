"""JSON shapes shared by the links endpoints (API contract: Schemas)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.modules.links.application.views import (
    LinkView,
    ModerationView,
    PersonView,
    ResourceView,
)
from app.shared.contracts.files import FileRef

from pydantic import BaseModel


class PersonRef(BaseModel):
    """Id and names of a person."""

    id: UUID
    first_name: str
    last_name: str


class UsedBy(BaseModel):
    """Where a file is used."""

    kind: Literal["link", "lesson", "chat"]
    id: UUID
    label: str


class FileItem(BaseModel):
    """A file as shown next to a link (the files module owns the full model)."""

    id: UUID
    name: str
    content_type: str
    byte_size: int
    purpose: str
    status: str
    reject_reason: str | None
    text_bytes: int | None
    assistant_ready: bool
    created_at: datetime
    expires_on: date | None
    used_by: list[UsedBy]


class LinkItem(BaseModel):
    """A short link, share or lesson resource owned by the caller."""

    id: UUID
    slug: str
    kind: Literal["url", "file", "chat", "flashcard_set"]
    url: str
    target_url: str | None
    file: FileItem | None
    title: str | None
    lesson_id: UUID | None
    target_id: UUID | None
    share_mode: Literal["snapshot", "live"] | None
    hits: int
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    disabled: bool


class ResourceItem(BaseModel):
    """A file or link attached to a lesson."""

    link_id: UUID
    lesson_id: UUID
    role: Literal["material", "attachment", "homework"]
    kind: Literal["url", "file"]
    short_url: str
    title: str
    author: PersonRef
    hidden: bool
    file: FileItem | None
    created_at: datetime


class ModerationItem(BaseModel):
    """A reported link with its owner."""

    link: LinkItem
    owner: PersonRef
    reports: int
    last_reported_at: datetime | None
    disabled_reason: str | None


def person(view: PersonView) -> PersonRef:
    """Map a person view to its JSON shape."""
    return PersonRef(id=view.id, first_name=view.first_name, last_name=view.last_name)


def file_item(file: FileRef | None, view: LinkView | ResourceView) -> FileItem | None:
    """Map a file contract object to the FileItem shape (best effort)."""
    if file is None:
        return None
    link = view.link
    label = link.title or file.name
    use = UsedBy(
        kind="lesson" if link.lesson_id else "link",
        id=link.lesson_id or link.id,
        label=label,
    )
    return FileItem(
        id=file.id,
        name=file.name,
        content_type=file.content_type,
        byte_size=file.byte_size,
        purpose=file.purpose.value,
        status=file.status,
        reject_reason=None,
        text_bytes=file.text_bytes,
        assistant_ready=file.status == "ready" and file.text_bytes is not None,
        created_at=link.created_at,
        expires_on=None,
        used_by=[use],
    )


def link_item(view: LinkView) -> LinkItem:
    """Map a LinkView to LinkItem."""
    link = view.link
    return LinkItem(
        id=link.id,
        slug=link.slug,
        kind=link.kind.value,
        url=view.url,
        target_url=link.target_url,
        file=file_item(view.file, view),
        title=link.title or (view.file.name if view.file else None),
        lesson_id=link.lesson_id,
        target_id=link.target_id,
        share_mode=link.share_mode.value if link.share_mode else None,
        hits=link.hits,
        created_at=link.created_at,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        disabled=link.is_disabled,
    )


def resource_item(view: ResourceView) -> ResourceItem:
    """Map a ResourceView to ResourceItem."""
    link = view.link
    assert link.lesson_id is not None and link.lesson_role is not None
    return ResourceItem(
        link_id=link.id,
        lesson_id=link.lesson_id,
        role=link.lesson_role.value,
        kind=link.kind.value,
        short_url=view.short_url,
        title=view.title,
        author=person(view.author),
        hidden=link.is_hidden,
        file=file_item(view.file, view),
        created_at=link.created_at,
    )


def moderation_item(view: ModerationView) -> ModerationItem:
    """Map a ModerationView to ModerationItem."""
    link = view.link.link
    owner = view.owner or PersonView(id=link.owner_id, first_name="", last_name="")
    return ModerationItem(
        link=link_item(view.link),
        owner=person(owner),
        reports=link.reports,
        last_reported_at=link.last_reported_at,
        disabled_reason=link.disabled_reason,
    )

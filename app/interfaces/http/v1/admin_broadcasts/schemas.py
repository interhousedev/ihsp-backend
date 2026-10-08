"""Request and response models of broadcasts (BroadcastInput, BroadcastItem)."""

from datetime import datetime
from uuid import UUID

from app.modules.admin.application.broadcast_view import BroadcastView
from app.modules.admin.domain.audience import Audience
from app.shared.actor import Role

from pydantic import BaseModel, Field


class AudienceBody(BaseModel):
    """Who receives a broadcast: everyone, or the union of roles, groups, semesters."""

    everyone: bool = False
    roles: list[Role] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)
    semesters: list[int] = Field(default_factory=list)

    def to_domain(self) -> Audience:
        """Convert to the domain audience."""
        return Audience(**self.model_dump())


class BroadcastInputBody(BaseModel):
    """Create a broadcast draft."""

    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    media_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    audience: AudienceBody


class BroadcastPatchBody(BaseModel):
    """Change some fields of a draft or scheduled broadcast."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    media_file_ids: list[UUID] | None = Field(default=None, max_length=10)
    audience: AudienceBody | None = None


class AudienceCountBody(BaseModel):
    """Count the recipients of an audience."""

    audience: AudienceBody


class AudienceCountResponse(BaseModel):
    """Number of recipients."""

    count: int


class SendBroadcastBody(BaseModel):
    """Send now (no time or a past time) or schedule."""

    scheduled_at: datetime | None = None


class PersonRefResponse(BaseModel):
    """PersonRef of the contract."""

    id: UUID
    first_name: str
    last_name: str


class BroadcastStatsResponse(BaseModel):
    """Delivery counts."""

    total: int
    sent: int
    failed: int
    blocked: int


class BroadcastResponse(BaseModel):
    """BroadcastItem of the contract."""

    id: UUID
    title: str
    text: str
    media_file_ids: list[UUID]
    audience: AudienceBody
    status: str
    scheduled_at: datetime | None
    created_via: str
    author: PersonRefResponse
    stats: BroadcastStatsResponse | None
    created_at: datetime

    @classmethod
    def from_view(cls, view: BroadcastView) -> "BroadcastResponse":
        """Build the response from a broadcast view."""
        broadcast, author = view.broadcast, view.author
        stats = view.stats
        return cls(
            id=broadcast.id,
            title=broadcast.title,
            text=broadcast.text,
            media_file_ids=broadcast.media_file_ids,
            audience=AudienceBody(**broadcast.audience.model_dump()),
            status=broadcast.status.value,
            scheduled_at=broadcast.scheduled_at,
            created_via=broadcast.created_via.value,
            author=PersonRefResponse(
                id=broadcast.author_id,
                first_name=author.first_name if author else "",
                last_name=author.last_name if author else "",
            ),
            stats=(
                BroadcastStatsResponse(
                    total=stats.total,
                    sent=stats.sent,
                    failed=stats.failed,
                    blocked=stats.blocked,
                )
                if stats
                else None
            ),
            created_at=broadcast.created_at,
        )

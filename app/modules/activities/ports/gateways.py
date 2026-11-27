"""Ports to other modules and to infrastructure."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.actor import Role
from app.shared.contracts.club_courses import CourseDirectory  # noqa: F401
from app.shared.notifications import NotificationDraft


class Notifier(Protocol):
    """Writes notifications; the recipient's settings choose the channel."""

    async def send(self, drafts: list[NotificationDraft]) -> None:
        """Queue notifications; a repeated dedupe key is dropped."""

    async def cancel_scheduled(
        self, prefix: str, *, user_id: UUID | None = None
    ) -> None:
        """Drop pending rows whose dedupe key starts with the prefix."""


class UserDirectory(Protocol):
    """What the module needs to know about people."""

    async def display_name(self, user_id: UUID) -> str:
        """Display name."""

    async def age(self, user_id: UUID) -> int | None:
        """Age in years when known."""

    async def is_student(self, user_id: UUID) -> bool:
        """Whether the person is a student."""

    async def holders(self, role: Role) -> list[UUID]:
        """People holding a global role."""

    async def graduating(self) -> set[UUID]:
        """Students in their final year."""


class Captcha(Protocol):
    """Bot check."""

    async def verify(self, token: str, ip: str) -> bool:
        """True when the token is valid."""


class ContactRelay(Protocol):
    """Delivers a visitor's message to a club owner's Telegram; nothing is stored."""

    async def reachable(self, user_id: UUID) -> bool:
        """Whether the person has a Telegram chat the bot can write to."""

    async def deliver(
        self, user_id: UUID, *, club_slug: str, name: str, email: str, body: str
    ) -> bool:
        """Send the message; False when no chat accepted it."""


class RateLimiter(Protocol):
    """Fixed-window limiter; raises `RateLimitedError` over the limit."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Count one hit."""


class AuditLog(Protocol):
    """Audit trail."""

    async def record(self, actor_id: UUID, action: str, target: UUID | None) -> None:
        """Write one audit row."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """An entry of the ONE opportunities catalog and where it is shown."""

    id: UUID
    draft: OpportunityDraft
    audience: frozenset[str]
    archived: bool
    lock_version: int

    @property
    def title(self) -> str:
        """Entry title."""
        return self.draft.title

    @property
    def kind(self) -> str:
        """Entry kind."""
        return self.draft.kind


class OpportunityCatalog(Protocol):
    """The admission catalog with the `audience` column (`admission`, `my_iht`)."""

    async def get(self, opportunity_id: UUID) -> CatalogEntry | None:
        """One entry."""

    async def list_all(self) -> list[CatalogEntry]:
        """Every entry."""

    async def references_ok(self, draft: OpportunityDraft) -> str | None:
        """The first invalid reference field (taxonomy, course, org) or None."""

    async def apply(
        self,
        draft: OpportunityDraft,
        audience: frozenset[str],
        *,
        target_id: UUID | None,
        by: UUID,
    ) -> UUID:
        """Create or overwrite an entry; an update bumps the lock version."""

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        """Hide or restore."""

    async def in_use(self, opportunity_id: UUID) -> bool:
        """Whether student plans or comments refer to it."""

    async def delete(self, opportunity_id: UUID) -> None:
        """Remove an unused entry."""

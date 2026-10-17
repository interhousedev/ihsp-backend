"""In-memory adapters of the mail module's ports and the contracts it consumes."""

import copy
import mimetypes
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.ports.mail_repository import MailRepository
from app.modules.mail.ports.outbound_relay import RelayResult
from app.modules.mail.ports.txt_resolver import DnsTemporaryError
from app.shared.actor import Actor, Role
from app.shared.base_error import GoneError, NotFoundError
from app.shared.contracts.files import (
    FilePurpose,
    FileRef,
    FileScope,
    TextPage,
)
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)
from app.shared.db.uow import AfterCommit
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft

# - - - Identity and suspension - - -


class FakeIdentity:
    """IdentityDirectory over a dict; only what the mail module reads is meaningful."""

    def __init__(self) -> None:
        """Start with no users."""
        self.users: dict[UUID, UserRef] = {}
        self.preferences: dict[UUID, UserPreferences] = {}

    def add_student(
        self,
        login: str | None = "aleksey.brastilov",
        *,
        first_name: str = "Aleksey",
        last_name: str = "Brastilov",
        status: UserStatus = UserStatus.ACTIVE,
        roles: frozenset[Role] = frozenset({Role.STUDENT}),
        forward_to_telegram: bool = True,
    ) -> UserRef:
        """Create a user (a student by default) and return its reference."""
        user = UserRef(
            id=new_id(),
            login=login,
            first_name=first_name,
            last_name=last_name,
            middle_name=None,
            roles=roles,
            status=status,
            locale="en",
            emis_status="active",
        )
        self.users[user.id] = user
        self.preferences[user.id] = UserPreferences(
            mail_forward_to_telegram=forward_to_telegram
        )
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the existing users among the ids."""
        return {i: self.users[i] for i in user_ids if i in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return the preferences (defaults for unknown users)."""
        return self.preferences.get(user_id, UserPreferences())

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """No user has a photo in this fake."""
        return {}

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Not used by the mail module."""
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Find an active user by login, case-insensitively."""
        for user in self.users.values():
            if user.login and user.login.lower() == login.lower():
                return user if user.status == UserStatus.ACTIVE else None
        return None

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Not used by the mail module."""
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of users holding any of the roles."""
        return [u.id for u in self.users.values() if u.roles & set(roles)]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Not used by the mail module."""
        return []

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Not used by the mail module."""

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Not used by the mail module."""


class FakeSuspension:
    """MailSuspension (reader and suspender) over a dict of reasons."""

    def __init__(self) -> None:
        """Start with nobody suspended."""
        self.reasons: dict[UUID, str] = {}

    async def is_suspended(self, user_id: UUID) -> bool:
        """True while the user has a suspension."""
        return user_id in self.reasons

    async def suspend(self, user_id: UUID, reason: str) -> None:
        """Record the suspension."""
        self.reasons[user_id] = reason

    def resume(self, user_id: UUID) -> None:
        """Lift the suspension (what an administrator does)."""
        self.reasons.pop(user_id, None)


# - - - Files - - -


class FakeFilesApi:
    """FilesApi that keeps bytes in memory and remembers what was asked."""

    def __init__(self) -> None:
        """Start empty."""
        self.refs: dict[UUID, FileRef] = {}
        self.blobs: dict[UUID, bytes] = {}
        self.expires: dict[UUID, int | None] = {}

    async def transfer_ownership(
        self, file_ids: Sequence[UUID], new_owner_id: UUID
    ) -> None:
        """Record the moves (the fake keeps no quota)."""
        self.transferred: list[tuple[UUID, UUID]] = [
            *getattr(self, "transferred", []),
            *((file_id, new_owner_id) for file_id in file_ids),
        ]

    async def get(self, file_id: UUID) -> FileRef | None:
        """Return the metadata or None."""
        return self.refs.get(file_id)

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the metadata of the files that exist."""
        return {i: self.refs[i] for i in file_ids if i in self.refs}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Return a fake URL."""
        return f"https://files.example.com/{file_id}"

    async def read_bytes(self, file_id: UUID) -> bytes:
        """Return the content; deleted files are gone, unknown ones not found."""
        ref = self.refs.get(file_id)
        if ref is None:
            raise NotFoundError()
        if ref.status == "deleted":
            raise GoneError()
        return self.blobs[file_id]

    async def read_text_page(self, file_id: UUID, page: int) -> TextPage:
        """Not used by the mail module."""
        raise NotFoundError()

    async def search_text(
        self, owner_id: UUID, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:  # any: the FilesApi contract returns plain dicts
        """Not used by the mail module."""
        return []

    async def store_bytes(
        self,
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
        data: bytes,
        expires_days: int | None = None,
    ) -> FileRef:
        """Keep the bytes and return a ready file."""
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        ref = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=name,
            content_type=content_type,
            byte_size=len(data),
            status="ready",
            text_bytes=None,
        )
        self.refs[ref.id] = ref
        self.blobs[ref.id] = data
        self.expires[ref.id] = expires_days
        return ref

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """The owner's ready files, newest first."""
        owned = [
            r
            for r in self.refs.values()
            if r.owner_id == owner_id and r.status == "ready"
        ]
        return list(reversed(owned))[:limit]

    async def check_access(self, file_id: UUID, actor: Actor) -> bool:
        """Owner only."""
        ref = self.refs.get(file_id)
        return ref is not None and ref.owner_id == actor.user_id

    def delete(self, file_id: UUID) -> None:
        """Mark a file deleted (what B6's expiry does after 30 days)."""
        ref = self.refs[file_id]
        self.refs[file_id] = FileRef(
            id=ref.id,
            owner_id=ref.owner_id,
            scope=ref.scope,
            purpose=ref.purpose,
            name=ref.name,
            content_type=ref.content_type,
            byte_size=ref.byte_size,
            status="deleted",
            text_bytes=None,
        )

    def stored_for(self, owner_id: UUID, name_suffix: str = "") -> list[FileRef]:
        """The files of an owner, optionally filtered by name ending."""
        return [
            r
            for r in self.refs.values()
            if r.owner_id == owner_id and r.name.endswith(name_suffix)
        ]


# - - - Checks, DNS and relay - - -


class FakeAuthenticator:
    """InboundAuthenticator that returns the configured results."""

    def __init__(self, checks: InboundChecks | None = None) -> None:
        """Start with 'nothing checked'."""
        self.checks = checks or InboundChecks()
        self.calls: list[dict[str, str]] = []

    async def check(
        self, raw: bytes, *, peer_ip: str, mail_from: str, helo: str
    ) -> InboundChecks:
        """Record the call and return the configured results."""
        self.calls.append({"peer_ip": peer_ip, "mail_from": mail_from, "helo": helo})
        return self.checks


class FakeTxtResolver:
    """TxtResolver over a dict; names listed in ``failing`` time out."""

    def __init__(self, records: dict[str, list[str]] | None = None) -> None:
        """Set the TXT records by name."""
        self.records = records or {}
        self.failing: set[str] = set()
        self.queries: list[str] = []

    async def txt(self, name: str) -> list[str]:
        """Return the records of the name."""
        self.queries.append(name)
        if name in self.failing:
            raise DnsTemporaryError(name)
        return self.records.get(name, [])


@dataclass(frozen=True, slots=True)
class RelayCall:
    """One message handed to the relay."""

    sender: str
    recipients: tuple[str, ...]
    raw: bytes


class FakeRelay:
    """OutboundRelay that records messages; ``errors`` are raised one per call."""

    def __init__(self) -> None:
        """Start accepting everything."""
        self.calls: list[RelayCall] = []
        self.errors: list[Exception] = []
        self.refused: tuple[str, ...] = ()

    async def send(
        self, *, sender: str, recipients: Sequence[str], raw: bytes
    ) -> RelayResult:
        """Raise the next queued error, else accept the message."""
        self.calls.append(RelayCall(sender, tuple(recipients), raw))
        if self.errors:
            raise self.errors.pop(0)
        return RelayResult(refused=self.refused)


class RecordingSleep:
    """A sleep that only records how long it was asked to wait."""

    def __init__(self) -> None:
        """Start with no waits."""
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        """Record the wait."""
        self.delays.append(seconds)


# - - - Repository and unit of work - - -


class InMemoryMailRepository:
    """MailRepository over a dict; rows are copied in and out like a database."""

    def __init__(self, rows: dict[UUID, MailMessage]) -> None:
        """Share the rows dict between all units of work."""
        self._rows = rows

    async def add(self, mail: MailMessage) -> bool:
        """Insert unless (user, direction, Message-ID) exists."""
        for row in self._rows.values():
            if (row.user_id, row.direction, row.message_id) == (
                mail.user_id,
                mail.direction,
                mail.message_id,
            ):
                return False
        self._rows[mail.id] = copy.deepcopy(mail)
        return True

    async def get(self, mail_id: UUID) -> MailMessage | None:
        """Return a copy of the row."""
        row = self._rows.get(mail_id)
        return None if row is None else copy.deepcopy(row)

    async def get_owned(self, user_id: UUID, mail_id: UUID) -> MailMessage | None:
        """Return the row only for its owner."""
        row = await self.get(mail_id)
        return row if row is not None and row.user_id == user_id else None

    async def save(self, mail: MailMessage) -> None:
        """Replace the row."""
        self._rows[mail.id] = copy.deepcopy(mail)

    async def inbound_exists(self, user_id: UUID, message_id: str) -> bool:
        """True if a received mail with this Message-ID exists."""
        return any(
            r.user_id == user_id
            and r.direction == MailDirection.IN
            and r.message_id == message_id
            for r in self._rows.values()
        )

    async def recent(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailMessage]:
        """Non-spam rows of the user, newest first."""
        rows = [
            r
            for r in self._rows.values()
            if r.user_id == user_id
            and r.status != MailStatus.SPAM
            and (before is None or r.occurred_at < before)
        ]
        rows.sort(key=lambda r: (r.occurred_at, r.id), reverse=True)
        return [copy.deepcopy(r) for r in rows[:limit]]

    async def sent(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailMessage]:
        """The user's sent rows, newest first."""
        rows = [
            r
            for r in self._rows.values()
            if r.user_id == user_id
            and r.direction == MailDirection.OUT
            and (before is None or r.occurred_at < before)
        ]
        rows.sort(key=lambda r: (r.occurred_at, r.id), reverse=True)
        return [copy.deepcopy(r) for r in rows[:limit]]

    async def find_outbound(
        self, user_id: UUID, message_ids: Sequence[str]
    ) -> MailMessage | None:
        """The user's sent mail with one of the Message-IDs."""
        for row in sorted(
            self._rows.values(), key=lambda r: r.occurred_at, reverse=True
        ):
            if (
                row.user_id == user_id
                and row.direction == MailDirection.OUT
                and row.message_id in message_ids
            ):
                return copy.deepcopy(row)
        return None

    async def unparsed_inbound(self, older_than: datetime, limit: int) -> list[UUID]:
        """Received or spam rows without ``parsed_at`` older than the moment."""
        rows = [
            r
            for r in self._rows.values()
            if r.direction == MailDirection.IN
            and r.status in (MailStatus.RECEIVED, MailStatus.SPAM)
            and r.occurred_at < older_than
            and r.meta.parsed_at is None
        ]
        rows.sort(key=lambda r: r.occurred_at)
        return [r.id for r in rows[:limit]]

    async def stale_queued(self, older_than: datetime, limit: int) -> list[UUID]:
        """Queued outbound rows older than the moment."""
        rows = [
            r
            for r in self._rows.values()
            if r.direction == MailDirection.OUT
            and r.status == MailStatus.QUEUED
            and r.occurred_at < older_than
        ]
        rows.sort(key=lambda r: r.occurred_at)
        return [r.id for r in rows[:limit]]

    def _bounces(self, since: datetime) -> list[MailMessage]:
        return [
            r
            for r in self._rows.values()
            if r.direction == MailDirection.OUT
            and r.status == MailStatus.BOUNCED
            and r.meta.bounced_at is not None
            and r.meta.bounced_at >= since
            and not r.meta.suspension_counted
        ]

    async def users_with_bounces(
        self, since: datetime, minimum: int
    ) -> dict[UUID, int]:
        """Uncounted bounces per user, for users with at least ``minimum``."""
        counts: dict[UUID, int] = {}
        for row in self._bounces(since):
            counts[row.user_id] = counts.get(row.user_id, 0) + 1
        return {u: n for u, n in counts.items() if n >= minimum}

    async def mark_bounces_counted(self, user_id: UUID, since: datetime) -> None:
        """Flag the user's bounces."""
        for row in self._bounces(since):
            if row.user_id == user_id:
                row.meta.suspension_counted = True

    async def delete_spam_before(self, cutoff: datetime) -> int:
        """Delete old spam rows."""
        doomed = [
            r.id
            for r in self._rows.values()
            if r.status == MailStatus.SPAM and r.occurred_at < cutoff
        ]
        for mail_id in doomed:
            del self._rows[mail_id]
        return len(doomed)

    async def flag_purged_before(self, cutoff: datetime) -> int:
        """Flag old rows as purged."""
        rows = [
            r
            for r in self._rows.values()
            if r.occurred_at < cutoff and not r.meta.purged
        ]
        for row in rows:
            row.meta.purged = True
        return len(rows)


@dataclass(slots=True)
class MailStore:
    """What the 'database' holds: rows, committed notifications and audit events."""

    rows: dict[UUID, MailMessage] = field(default_factory=dict)
    notifications: list[NotificationDraft] = field(default_factory=list)
    audits: list[AuditDraft] = field(default_factory=list)

    def all(self) -> list[MailMessage]:
        """All rows, oldest first."""
        return sorted(self.rows.values(), key=lambda r: (r.occurred_at, r.id))


class FakeMailUnitOfWork:
    """MailUnitOfWork: notifications and audits land in the store only on commit."""

    def __init__(self, store: MailStore) -> None:
        """Bind to the shared store."""
        self._store = store
        self.mail: MailRepository = InMemoryMailRepository(store.rows)
        self._notifications: list[NotificationDraft] = []
        self._audits: list[AuditDraft] = []
        self._hooks: list[AfterCommit] = []

    async def __aenter__(self) -> Self:
        """Open the (fake) transaction."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications until commit."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events until commit."""
        self._audits.extend(drafts)

    def after_commit(self, hook: AfterCommit) -> None:
        """Queue a hook until commit."""
        self._hooks.append(hook)

    async def commit(self) -> None:
        """Publish drafts (a repeated dedupe key is ignored, like the real outbox)."""
        known = {n.dedupe_key for n in self._store.notifications}
        for draft in self._notifications:
            if draft.dedupe_key not in known:
                self._store.notifications.append(draft)
                known.add(draft.dedupe_key)
        self._store.audits.extend(self._audits)
        self._notifications, self._audits = [], []
        hooks, self._hooks = self._hooks, []
        for hook in hooks:
            await hook()

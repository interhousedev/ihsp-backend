"""In-memory unit of work and repositories for the identity use cases."""

import copy
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.modules.identity.domain.audit_event import AuditEventRecord
from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft
from app.shared.pagination import Page, decode_cursor, encode_cursor


@dataclass
class IdentityStore:
    """All rows of one fake database."""

    users: dict[UUID, User] = field(default_factory=dict)
    sessions: dict[UUID, LoginSession] = field(default_factory=dict)
    links: dict[int, TelegramLink] = field(default_factory=dict)
    connectors: dict[UUID, McpConnector] = field(default_factory=dict)
    events: list[AuditEventRecord] = field(default_factory=list)
    notifications: list[NotificationDraft] = field(default_factory=list)
    audits: list[AuditDraft] = field(default_factory=list)

    def snapshot(self) -> tuple[Any, ...]:
        """Copy the tables so an uncommitted unit of work can be rolled back."""
        return copy.deepcopy(
            (self.users, self.sessions, self.links, self.connectors, self.events)
        )

    def restore(self, snap: tuple[Any, ...]) -> None:
        """Put a snapshot back."""
        self.users, self.sessions, self.links, self.connectors, self.events = snap

    def audit_types(self, user_id: UUID | None = None) -> list[str]:
        """Types of the committed audit drafts (optionally of one user)."""
        return [a.type for a in self.audits if user_id in (None, a.user_id)]

    def notification_types(self) -> list[str]:
        """Types of the committed notification drafts."""
        return [n.type.value for n in self.notifications]


def _copy[T](value: T) -> T:
    return copy.deepcopy(value)


class FakeUserRepository:
    """UserRepository over the store."""

    def __init__(self, store: IdentityStore) -> None:
        """Bind to the store."""
        self._s = store

    async def get(self, user_id: UUID) -> User | None:
        """Return a copy of the user."""
        user = self._s.users.get(user_id)
        return _copy(user) if user else None

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """Return copies of the existing users."""
        return {
            uid: _copy(self._s.users[uid]) for uid in user_ids if uid in self._s.users
        }

    def _find(self, predicate: Callable[[User], bool]) -> User | None:
        found = next((u for u in self._s.users.values() if predicate(u)), None)
        return _copy(found) if found else None

    async def get_by_login(self, login: str) -> User | None:
        """Case-insensitive login lookup."""
        return self._find(lambda u: (u.login or "").lower() == login.strip().lower())

    async def get_by_recovery_email(self, email: str) -> User | None:
        """Case-insensitive email lookup."""
        return self._find(
            lambda u: (u.recovery_email or "").lower() == email.strip().lower()
        )

    async def get_by_emis_teacher_id(self, emis_teacher_id: int) -> User | None:
        """Lookup by EMIS teacher id."""
        return self._find(lambda u: u.emis_teacher_id == emis_teacher_id)

    async def list_with_roles(self, roles: Sequence[Role]) -> list[User]:
        """Copies of users holding any role, except deleted and deactivated ones."""
        return [
            _copy(u)
            for u in self._s.users.values()
            if u.roles & set(roles)
            and u.status not in (UserStatus.DELETED, UserStatus.DEACTIVATED)
        ]

    async def get_by_activation_hash(self, token_hash: str) -> User | None:
        """Lookup by activation token hash."""
        return self._find(lambda u: u.activation_token_hash == token_hash)

    async def get_by_otp_reset_request(self, request_id: UUID) -> User | None:
        """Lookup by OTP reset request id."""
        return self._find(lambda u: u.otp_reset_request_id == request_id)

    async def add(self, user: User) -> None:
        """Insert a user."""
        self._s.users[user.id] = _copy(user)

    async def save(self, user: User) -> None:
        """Replace a user."""
        if user.id not in self._s.users:
            raise LookupError(str(user.id))
        self._s.users[user.id] = _copy(user)

    async def logins_with_prefix(self, prefix: str) -> set[str]:
        """Lowercase logins starting with the prefix."""
        return {
            u.login.lower()
            for u in self._s.users.values()
            if u.login and u.login.lower().startswith(prefix.lower())
        }

    async def email_taken(
        self, email: str, *, except_user_id: UUID | None = None
    ) -> bool:
        """Is the email another user's recovery email?"""
        return any(
            (u.recovery_email or "").lower() == email.strip().lower()
            and u.id != except_user_id
            for u in self._s.users.values()
        )

    async def ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Active users with any of the roles."""
        return [
            u.id for u in self._s.users.values() if u.is_active and u.roles & set(roles)
        ]

    async def search(
        self,
        *,
        query: str | None,
        roles: Sequence[Role],
        status: UserStatus | None,
        cursor: str | None,
        limit: int,
    ) -> Page[User]:
        """Newest (highest id) first."""
        users = sorted(self._s.users.values(), key=lambda u: u.id, reverse=True)
        if query:
            q = query.lower()
            users = [
                u
                for u in users
                if q in " ".join([u.login or "", u.first_name, u.last_name]).lower()
            ]
        if roles:
            users = [u for u in users if u.roles & set(roles)]
        if status:
            users = [u for u in users if u.status == status]
        decoded = decode_cursor(cursor)
        if decoded:
            users = [u for u in users if str(u.id) < decoded["id"]]
        page = users[: limit + 1]
        items = [_copy(u) for u in page[:limit]]
        more = len(page) > limit
        return Page[User](
            items=items,
            next_cursor=encode_cursor({"id": str(items[-1].id)}) if more else None,
        )

    async def search_active(
        self, query: str, *, roles: Sequence[Role], limit: int
    ) -> list[User]:
        """Active users matching every word."""
        words = query.lower().split()
        found = [
            _copy(u)
            for u in self._s.users.values()
            if u.is_active
            and all(
                w in " ".join([u.login or "", u.first_name, u.last_name]).lower()
                for w in words
            )
            and (not roles or u.roles & set(roles))
        ]
        return found[:limit]

    async def due_otp_resets(self, now: datetime) -> list[User]:
        """Users whose OTP reset is due."""
        return [
            _copy(u)
            for u in self._s.users.values()
            if u.otp_reset_effective_at and u.otp_reset_effective_at <= now
        ]

    async def purgeable(self, deleted_before: datetime, limit: int) -> list[User]:
        """Deleted users not yet anonymized."""
        return [
            _copy(u)
            for u in self._s.users.values()
            if u.status == UserStatus.DELETED
            and u.deleted_at
            and u.deleted_at < deleted_before
            and u.first_name != "Deleted"
        ][:limit]

    async def merge_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge the patch into the stored preferences."""
        user = self._s.users[user_id]
        user.preferences = {**user.preferences, **patch}
        return dict(user.preferences)

    async def get_epoch(self, user_id: UUID) -> int | None:
        """The user's auth epoch."""
        user = self._s.users.get(user_id)
        return user.auth_epoch if user else None


class FakeSessionRepository:
    """SessionRepository over the store."""

    def __init__(self, store: IdentityStore) -> None:
        """Bind to the store."""
        self._s = store

    async def add(self, session: LoginSession) -> None:
        """Insert a session."""
        self._s.sessions[session.id] = _copy(session)

    async def save(self, session: LoginSession) -> None:
        """Replace a session."""
        self._s.sessions[session.id] = _copy(session)

    async def get(self, session_id: UUID) -> LoginSession | None:
        """Return a copy."""
        found = self._s.sessions.get(session_id)
        return _copy(found) if found else None

    async def get_by_hydra_sid(self, hydra_sid: str) -> LoginSession | None:
        """Lookup by Hydra session id."""
        found = next(
            (s for s in self._s.sessions.values() if s.hydra_sid == hydra_sid), None
        )
        return _copy(found) if found else None

    def _active(self, user_id: UUID, now: datetime) -> list[LoginSession]:
        return [
            s
            for s in self._s.sessions.values()
            if s.user_id == user_id and s.is_active(now)
        ]

    async def list_active(self, user_id: UUID, now: datetime) -> list[LoginSession]:
        """Most recently seen first."""
        active = sorted(
            self._active(user_id, now), key=lambda s: s.last_seen_at, reverse=True
        )
        return [_copy(s) for s in active]

    async def latest_active(
        self, user_id: UUID, now: datetime, *, amr: list[str] | None = None
    ) -> LoginSession | None:
        """Most recently created active session, optionally with a given amr."""
        active = sorted(self._active(user_id, now), key=lambda s: s.id)
        if amr is not None:
            active = [s for s in active if list(s.amr) == amr]
        return _copy(active[-1]) if active else None

    async def revoke(self, session_id: UUID, now: datetime) -> LoginSession | None:
        """Revoke an active session."""
        session = self._s.sessions.get(session_id)
        if session is None or session.revoked_at is not None:
            return None
        session.revoked_at = now
        return _copy(session)

    async def revoke_all(
        self, user_id: UUID, now: datetime, *, except_id: UUID | None = None
    ) -> list[LoginSession]:
        """Revoke every unrevoked session of the user."""
        revoked: list[LoginSession] = []
        for session in self._s.sessions.values():
            if (
                session.user_id == user_id
                and session.revoked_at is None
                and session.id != except_id
            ):
                session.revoked_at = now
                revoked.append(_copy(session))
        return revoked

    async def touch(
        self, session_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Update last_seen_at unless touched recently."""
        session = self._s.sessions.get(session_id)
        if session and session.last_seen_at < now - min_interval:
            session.last_seen_at = now


class FakeTelegramLinkRepository:
    """TelegramLinkRepository over the store."""

    def __init__(self, store: IdentityStore) -> None:
        """Bind to the store."""
        self._s = store

    async def get(self, telegram_user_id: int) -> TelegramLink | None:
        """Return a copy."""
        found = self._s.links.get(telegram_user_id)
        return _copy(found) if found else None

    async def list_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Links of the user."""
        return [
            _copy(link) for link in self._s.links.values() if link.user_id == user_id
        ]

    async def list_for_users(
        self, user_ids: Sequence[UUID]
    ) -> dict[UUID, list[TelegramLink]]:
        """Links of several users."""
        return {uid: await self.list_for_user(uid) for uid in user_ids}

    async def add(self, link: TelegramLink) -> None:
        """Insert a link."""
        self._s.links[link.telegram_user_id] = _copy(link)

    async def save(self, link: TelegramLink) -> None:
        """Replace a link."""
        self._s.links[link.telegram_user_id] = _copy(link)

    async def delete(self, telegram_user_id: int) -> bool:
        """Delete a link."""
        return self._s.links.pop(telegram_user_id, None) is not None

    async def delete_all_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Delete every link of the user."""
        gone = [link for link in self._s.links.values() if link.user_id == user_id]
        for link in gone:
            del self._s.links[link.telegram_user_id]
        return gone


class FakeConnectorRepository:
    """ConnectorRepository over the store."""

    def __init__(self, store: IdentityStore) -> None:
        """Bind to the store."""
        self._s = store

    async def add(self, connector: McpConnector) -> None:
        """Insert a connector."""
        self._s.connectors[connector.id] = _copy(connector)

    async def get(self, connector_id: UUID) -> McpConnector | None:
        """Return a copy."""
        found = self._s.connectors.get(connector_id)
        return _copy(found) if found else None

    async def get_by_token_hash(self, token_hash: str) -> McpConnector | None:
        """Lookup by token hash."""
        found = next(
            (c for c in self._s.connectors.values() if c.token_hash == token_hash),
            None,
        )
        return _copy(found) if found else None

    async def list_for_user(self, user_id: UUID) -> list[McpConnector]:
        """Newest first."""
        found = sorted(
            (c for c in self._s.connectors.values() if c.user_id == user_id),
            key=lambda c: c.id,
            reverse=True,
        )
        return [_copy(c) for c in found]

    async def save(self, connector: McpConnector) -> None:
        """Replace a connector."""
        self._s.connectors[connector.id] = _copy(connector)

    async def revoke_all_for_user(
        self, user_id: UUID, now: datetime
    ) -> list[McpConnector]:
        """Revoke the active connectors of the user."""
        revoked: list[McpConnector] = []
        for connector in self._s.connectors.values():
            if connector.user_id == user_id and connector.revoked_at is None:
                connector.revoked_at = now
                revoked.append(_copy(connector))
        return revoked

    async def last_used_by_client(
        self, client_ids: Sequence[str]
    ) -> dict[str, datetime | None]:
        """Latest use per Hydra client."""
        result: dict[str, datetime | None] = dict.fromkeys(client_ids)
        for connector in self._s.connectors.values():
            cid = connector.hydra_client_id
            if cid in result and connector.last_used_at:
                current = result[cid]
                if current is None or connector.last_used_at > current:
                    result[cid] = connector.last_used_at
        return result

    async def touch_last_used(
        self, connector_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Update last_used_at unless touched recently."""
        connector = self._s.connectors.get(connector_id)
        if connector and (
            connector.last_used_at is None
            or connector.last_used_at < now - min_interval
        ):
            connector.last_used_at = now


class FakeAuditEventRepository:
    """AuditEventRepository over the store."""

    def __init__(self, store: IdentityStore) -> None:
        """Bind to the store."""
        self._s = store

    async def search(
        self,
        *,
        user_id: UUID | None,
        type: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AuditEventRecord]:
        """Newest first."""
        events = sorted(
            self._s.events, key=lambda e: (e.created_at, e.id), reverse=True
        )
        events = [
            e
            for e in events
            if (user_id is None or e.user_id == user_id)
            and (type is None or e.type == type)
            and (since is None or e.created_at >= since)
            and (until is None or e.created_at <= until)
        ]
        decoded = decode_cursor(cursor)
        if decoded:
            marker = (datetime.fromisoformat(decoded["at"]), UUID(decoded["id"]))
            events = [e for e in events if (e.created_at, e.id) < marker]
        page = events[: limit + 1]
        items = page[:limit]
        next_cursor = None
        if len(page) > limit:
            last = items[-1]
            next_cursor = encode_cursor(
                {"at": last.created_at.isoformat(), "id": str(last.id)}
            )
        return Page[AuditEventRecord](items=items, next_cursor=next_cursor)

    async def recent_for_user(
        self, user_id: UUID, limit: int
    ) -> list[AuditEventRecord]:
        """The latest events of a user."""
        page = await self.search(
            user_id=user_id, type=None, since=None, until=None, cursor=None, limit=limit
        )
        return page.items


class FakeIdentityUnitOfWork:
    """Transaction semantics over the store: rollback unless committed."""

    def __init__(self, store: IdentityStore, clock: Clock) -> None:
        """Create repositories bound to the store."""
        self._store = store
        self._clock = clock
        self.users = FakeUserRepository(store)
        self.sessions = FakeSessionRepository(store)
        self.telegram_links = FakeTelegramLinkRepository(store)
        self.connectors = FakeConnectorRepository(store)
        self.audit_events = FakeAuditEventRepository(store)
        self.committed = False
        self._snapshot: tuple[Any, ...] = ()
        self._notifications: list[NotificationDraft] = []
        self._audits: list[AuditDraft] = []
        self._hooks: list[Callable[[], Awaitable[None]]] = []

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        self._snapshot = self._store.snapshot()
        self._notifications, self._audits, self._hooks = [], [], []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back everything since the last commit."""
        self._store.restore(self._snapshot)

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audits.extend(drafts)

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Queue a hook."""
        self._hooks.append(hook)

    async def commit(self) -> None:
        """Make the changes permanent, store drafts, run hooks."""
        self._store.notifications.extend(self._notifications)
        self._store.audits.extend(self._audits)
        for draft in self._audits:
            self._store.events.append(
                AuditEventRecord(
                    id=new_id(),
                    type=draft.type,
                    created_at=self._clock.now(),
                    user_id=draft.user_id,
                    actor_id=draft.actor_id,
                    ip=draft.ip,
                    user_agent=draft.user_agent,
                    metadata=dict(draft.metadata or {}),
                )
            )
        self._notifications, self._audits = [], []
        self._snapshot = self._store.snapshot()
        self.committed = True
        hooks, self._hooks = self._hooks, []
        for hook in hooks:
            await hook()

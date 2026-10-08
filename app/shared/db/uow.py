"""Unit of work: one transaction per use case (outbox, audit, after-commit)."""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self

from app.shared.notifications import AuditDraft, NotificationDraft

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

OutboxWriter = Callable[[AsyncSession, list[NotificationDraft]], Awaitable[None]]
AuditWriter = Callable[[AsyncSession, list[AuditDraft]], Awaitable[None]]
AfterCommit = Callable[[], Awaitable[None]]


class SqlUnitOfWork:
    """Base unit of work; modules subclass it and create repositories in _init_repos."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        outbox_writer: OutboxWriter,
        audit_writer: AuditWriter,
        outbox_committed_hook: AfterCommit | None = None,
    ) -> None:
        """Store factories; the session is opened in __aenter__."""
        self._sessionmaker = sessionmaker
        self._outbox_writer = outbox_writer
        self._audit_writer = audit_writer
        self._outbox_committed_hook = outbox_committed_hook
        self._outbox: list[NotificationDraft] = []
        self._audit: list[AuditDraft] = []
        self._after_commit: list[AfterCommit] = []
        self.session: AsyncSession

    async def __aenter__(self) -> Self:
        """Open a session and a transaction."""
        self.session = self._sessionmaker()
        await self.session.begin()
        self._outbox, self._audit, self._after_commit = [], [], []
        self._init_repos()
        return self

    def _init_repos(self) -> None:
        """Create repositories bound to self.session (override in modules)."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed; always close the session."""
        try:
            if self.session.in_transaction():
                await self.session.rollback()
        finally:
            await self.session.close()

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
        self._outbox.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events to insert at commit."""
        self._audit.extend(drafts)

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit (e.g. kick a task)."""
        self._after_commit.append(hook)

    async def commit(self) -> None:
        """Write outbox and audit rows, commit, then run after-commit hooks."""
        had_outbox = bool(self._outbox)
        if self._outbox:
            await self._outbox_writer(self.session, self._outbox)
        if self._audit:
            await self._audit_writer(self.session, self._audit)
        await self.session.commit()
        self._outbox, self._audit = [], []
        if had_outbox and self._outbox_committed_hook is not None:
            self._after_commit.append(self._outbox_committed_hook)
        hooks, self._after_commit = self._after_commit, []
        for hook in hooks:
            await hook()

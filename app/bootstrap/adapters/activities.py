"""Adapters the activities module needs: repositories, notices, people, courses."""

from collections.abc import Callable
from html import escape
from typing import Any
from uuid import UUID

from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.identity.infrastructure.audit_writer import write_audit_events
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.infrastructure.orm.course_staff import CourseStaff
from app.modules.notify.domain.notification_status import NotificationStatus
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.infrastructure.tables import notifications_table
from app.settings import ActivitiesSettings
from app.shared.actor import Role
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.notify import TelegramSender
from app.shared.i18n.core import I18nCore
from app.shared.notifications import AuditDraft, NotificationDraft

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Sessions = async_sessionmaker[AsyncSession]

log = structlog.get_logger(__name__)
_TURNSTILE_TIMEOUT = httpx.Timeout(5.0)


class PerCall:
    """A repository whose every call runs in its own committed transaction.

    `repo(session)` builds the SQL repository; the services keep one long-lived
    instance, so a session must never outlive a single call.
    """

    def __init__(self, sessions: Sessions, repo: Callable[[AsyncSession], Any]) -> None:
        """Keep the sessionmaker and the repository factory."""
        self._sessions = sessions
        self._repo = repo

    def __getattr__(self, name: str) -> Any:
        """Return an async callable running the repository method in a transaction."""
        if name.startswith("_"):
            raise AttributeError(name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            async with self._sessions() as session, session.begin():
                return await getattr(self._repo(session), name)(*args, **kwargs)

        return call


def per_call(sessions: Sessions, repo: Callable[[AsyncSession], Any]) -> Any:
    """Wrap a repository factory as the port `T`; each call opens a session."""
    return PerCall(sessions, repo)


class ActivitiesNotifier:
    """Notifier: rows go to the outbox; the recipient's settings pick the channel."""

    def __init__(self, sessions: Sessions) -> None:
        """Keep the sessionmaker."""
        self._sessions = sessions

    async def send(self, drafts: list[NotificationDraft]) -> None:
        """Queue notifications; a repeated dedupe key is dropped."""
        async with self._sessions() as session, session.begin():
            await write_notifications(session, drafts)

    async def cancel_scheduled(
        self, prefix: str, *, user_id: UUID | None = None
    ) -> None:
        """Cancel pending rows whose dedupe key starts with the prefix."""
        table = notifications_table()
        like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cond = [
            table.c.dedupe_key.like(f"{like}%", escape="\\"),
            table.c.status == NotificationStatus.PENDING.value,
        ]
        if user_id is not None:
            cond.append(table.c.user_id == user_id)
        async with self._sessions() as session, session.begin():
            await session.execute(
                sa.update(table)
                .where(*cond)
                .values(status=NotificationStatus.CANCELLED.value, next_attempt_at=None)
            )


class ActivitiesUsers:
    """UserDirectory over identity and the academic student table."""

    def __init__(self, identity: IdentityDirectory, sessions: Sessions) -> None:
        """Keep the identity directory and the sessionmaker."""
        self._identity = identity
        self._sessions = sessions

    async def display_name(self, user_id: UUID) -> str:
        """First and last name; empty when the person is gone."""
        user = await self._identity.get_user(user_id)
        return f"{user.first_name} {user.last_name}".strip() if user else ""

    async def age(self, user_id: UUID) -> int | None:
        """The platform stores no birth date, so the age is unknown."""
        return None

    async def is_student(self, user_id: UUID) -> bool:
        """Whether the person holds the student role."""
        user = await self._identity.get_user(user_id)
        return user is not None and Role.STUDENT in user.roles

    async def holders(self, role: Role) -> list[UUID]:
        """People holding the global role."""
        return list(await self._identity.user_ids_with_roles([role]))

    async def graduating(self) -> set[UUID]:
        """Active students of the highest course year."""
        async with self._sessions() as session:
            top = select(func.max(Group.course)).scalar_subquery()
            rows = await session.scalars(
                select(Student.user_id)
                .join(Group, Group.id == Student.group_id)
                .where(Student.status == "active", Group.course == top)
            )
            return set(rows)


class ActivitiesAudit:
    """AuditLog over the identity audit trail."""

    def __init__(self, sessions: Sessions) -> None:
        """Keep the sessionmaker."""
        self._sessions = sessions

    async def record(self, actor_id: UUID, action: str, target: UUID | None) -> None:
        """Write one audit row."""
        draft = AuditDraft(
            type=action,
            user_id=target,
            actor_id=actor_id,
            metadata={"target": str(target)} if target else None,
        )
        async with self._sessions() as session, session.begin():
            await write_audit_events(session, [draft])


class ActivitiesCaptcha:
    """Cloudflare Turnstile; `fake` mode accepts any non-blank token."""

    def __init__(
        self,
        settings: ActivitiesSettings,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Keep the settings and an optional HTTP client (tests)."""
        self._settings = settings
        self._http = http

    async def verify(self, token: str, ip: str) -> bool:
        """True when Turnstile accepts the token; any failure is a refusal."""
        if not token.strip():
            return False
        if self._settings.turnstile_mode == "fake":
            return True
        secret = self._settings.turnstile_secret.get_secret_value()
        if not secret:
            log.error("turnstile_secret_missing")
            return False
        data = {"secret": secret, "response": token}
        if ip and ip != "unknown":
            data["remoteip"] = ip
        try:
            if self._http is not None:
                resp = await self._http.post(
                    self._settings.turnstile_verify_url, data=data
                )
            else:
                async with httpx.AsyncClient(timeout=_TURNSTILE_TIMEOUT) as client:
                    resp = await client.post(
                        self._settings.turnstile_verify_url, data=data
                    )
            resp.raise_for_status()
            return bool(resp.json().get("success"))
        except (httpx.HTTPError, ValueError):
            log.warning("turnstile_verify_failed", exc_info=True)
            return False


class ActivitiesContactRelay:
    """Sends a visitor's message to the club owner's linked Telegram chats."""

    def __init__(
        self,
        identity: IdentityDirectory,
        telegram: TelegramSender | None,
        i18n: I18nCore,
    ) -> None:
        """Keep the identity directory, the Telegram sender and the translations."""
        self._identity = identity
        self._telegram = telegram
        self._i18n = i18n

    async def _chats(self, user_id: UUID) -> list[int]:
        if self._telegram is None:
            return []
        accounts = await self._identity.telegram_accounts(user_id)
        return [a.telegram_user_id for a in accounts if not a.blocked]

    async def reachable(self, user_id: UUID) -> bool:
        """Whether the person has a Telegram chat that did not block the bot."""
        return bool(await self._chats(user_id))

    async def deliver(
        self, user_id: UUID, *, club_slug: str, name: str, email: str, body: str
    ) -> bool:
        """Send to every linked chat; True when at least one accepted it."""
        if self._telegram is None:
            return False
        user = await self._identity.get_user(user_id)
        ctx = self._i18n.get_context((user.locale if user else None) or "ru")
        text = ctx.get(
            "activities-contact-telegram",
            club=escape(club_slug),
            name=escape(name),
            email=escape(email),
            body=escape(body),
        )
        sent = False
        for chat in await self._chats(user_id):
            try:
                await self._telegram.send_message(chat, text)
                sent = True
            except Exception:  # noqa: BLE001 - one dead chat must not block others
                log.warning("club_contact_telegram_failed", exc_info=True)
        return sent


class LmsCourseDirectory:
    """CourseDirectory over the LMS course and course-staff tables."""

    def __init__(self, sessions: Sessions) -> None:
        """Keep the sessionmaker."""
        self._sessions = sessions

    async def exists(self, course_id: UUID) -> bool:
        """Whether the course exists."""
        async with self._sessions() as session:
            return await session.get(Course, course_id) is not None

    async def is_staff(self, course_id: UUID, user_id: UUID) -> bool:
        """Whether the person created the course or is on its staff."""
        async with self._sessions() as session:
            course = await session.get(Course, course_id)
            if course is None:
                return False
            if course.created_by == user_id:
                return True
            row = await session.scalar(
                select(CourseStaff.id).where(
                    CourseStaff.course_id == course_id, CourseStaff.user_id == user_id
                )
            )
            return row is not None

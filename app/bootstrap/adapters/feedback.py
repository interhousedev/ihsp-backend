"""Adapters of the feedback module: people (identity, academic) and mail."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.feedback.ports.people import Person
from app.shared.actor import Role
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.contracts.mail import MailApi


class FeedbackPeopleAdapter:
    """Users from identity, the group of students from academic."""

    def __init__(
        self, identity: IdentityDirectory, schedule: ScheduleQueries | None
    ) -> None:
        """Store the directories (``schedule`` is None in processes without it)."""
        self.identity = identity
        self.schedule = schedule

    async def person(self, user_id: UUID) -> Person | None:
        """Return the user or None."""
        return (await self.people([user_id])).get(user_id)

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """Return the users that exist."""
        users = await self.identity.get_users(list(user_ids))
        return {user_id: await self._person(user) for user_id, user in users.items()}

    async def admin_ids(self) -> list[UUID]:
        """Return every administrator."""
        return await self.identity.user_ids_with_roles([Role.ADMIN])

    async def _person(self, user: UserRef) -> Person:
        accounts = await self.identity.telegram_accounts(user.id)
        return Person(
            user_id=user.id,
            display_name=f"{user.last_name} {user.first_name}".strip(),
            roles=tuple(sorted(role.value for role in user.roles)),
            locale=user.locale,
            group_name=await self._group(user),
            login=user.login,
            has_telegram=any(not account.blocked for account in accounts),
        )

    async def _group(self, user: UserRef) -> str | None:
        if self.schedule is None or Role.STUDENT not in user.roles:
            return None
        student = await self.schedule.get_student(user.id)
        return student.group_name if student else None


class FeedbackMailAdapter:
    """Sends a response from the administrator's mailbox (mail module)."""

    def __init__(self, mail: MailApi) -> None:
        """Store the mail module's API."""
        self.mail = mail

    async def send(
        self, *, sender_id: UUID, to_login: str, subject: str, html: str
    ) -> None:
        """Queue the mail to the login's platform address."""
        await self.mail.send(
            sender_id, to=[self.mail.address_of(to_login)], subject=subject, html=html
        )

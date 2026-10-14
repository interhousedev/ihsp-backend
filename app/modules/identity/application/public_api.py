"""Implementations of the IdentityDirectory and IdentityCommands contracts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.ensure_teacher import ensure_teacher
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.photo_files import PhotoUrls
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.application.update_preferences import UpdatePreferences
from app.modules.identity.domain.audit_event import TELEGRAM_UNLINKED
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker


def _ref(user: User) -> UserRef:
    return user.to_ref()


@dataclass(frozen=True, slots=True)
class IdentityDirectoryImpl:
    """Read access to users for other modules."""

    uow_factory: UowFactory
    clock: Clock
    photos: PhotoUrls

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
        return _ref(user) if user else None

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the existing users among the ids."""
        async with self.uow_factory() as uow:
            users = await uow.users.get_many(user_ids)
        return {uid: _ref(user) for uid, user in users.items()}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return the preferences with defaults filled in."""
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
        return UserPreferences.model_validate(user.preferences if user else {})

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return short-lived photo URLs; users without a photo are left out."""
        if not user_ids:
            return {}
        async with self.uow_factory() as uow:
            users = await uow.users.get_many(user_ids)
        return await self.photos.of_users(users.values())

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Return the user a Telegram account is linked to."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            user = await uow.users.get(link.user_id) if link else None
        return _ref(user) if user else None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Find an active user by login, case-insensitively."""
        async with self.uow_factory() as uow:
            user = await uow.users.get_by_login(login)
        return _ref(user) if user and user.is_active else None

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Return the Telegram accounts linked to the user."""
        async with self.uow_factory() as uow:
            links = await uow.telegram_links.list_for_user(user_id)
        return [link.to_ref() for link in links]

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of active users holding any of the roles."""
        async with self.uow_factory() as uow:
            return await uow.users.ids_with_roles(roles)

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Search active users by name or login."""
        async with self.uow_factory() as uow:
            users = await uow.users.search_active(query, roles=roles, limit=limit)
        return [_ref(user) for user in users]

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Mark that a Telegram account blocked (or unblocked) the bot."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            if link is None:
                return
            link.blocked_at = self.clock.now() if blocked else None
            await uow.telegram_links.save(link)
            await uow.commit()

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Refresh the cached Telegram username and name."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            if link is None:
                return
            link.username = username
            link.first_name = first_name
            link.last_seen_at = self.clock.now()
            await uow.telegram_links.save(link)
            await uow.commit()


@dataclass(frozen=True, slots=True)
class IdentityCommandsImpl:
    """Write access to users for other modules."""

    uow_factory: UowFactory
    clock: Clock
    preferences: UpdatePreferences
    revoker: AccessRevoker
    kicker: TaskKicker

    async def create_unregistered_student(
        self,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
        emis_student_id: int | None,
    ) -> UserRef:
        """Create a student who has not registered yet (EMIS import)."""
        user = User(
            id=new_id(),
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            roles={Role.STUDENT},
            status=UserStatus.UNREGISTERED,
            emis_student_id=emis_student_id,
        )
        async with self.uow_factory() as uow:
            await uow.users.add(user)
            await uow.commit()
        return _ref(user)

    async def ensure_teacher(
        self,
        *,
        emis_teacher_id: int | None,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> UserRef:
        """Find or create a teacher named by an EMIS timetable."""
        return await ensure_teacher(
            self.uow_factory,
            emis_teacher_id=emis_teacher_id,
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
        )

    async def set_emis_status(
        self, user_id: UUID, status: Literal["active", "needs_reauth"]
    ) -> None:
        """Set whether the stored EMIS password still works."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            user.emis_status = status
            await uow.users.save(user)
            await uow.commit()

    async def update_names(
        self,
        user_id: UUID,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> None:
        """Update the user's names from EMIS."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            user.first_name = first_name
            user.last_name = last_name
            user.middle_name = middle_name
            await uow.users.save(user)
            await uow.commit()

    async def update_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> UserPreferences:
        """Merge a partial preferences dict and return the result."""
        return await self.preferences.for_user(user_id, patch)

    async def unlink_telegram(self, telegram_user_id: int) -> None:
        """Remove a Telegram link (the bot's Log out button)."""
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user_id)
            if link is None:
                return
            await uow.telegram_links.delete(telegram_user_id)
            uow.audit(
                make_audit(
                    TELEGRAM_UNLINKED,
                    user_id=link.user_id,
                    telegram_user_id=telegram_user_id,
                    via="bot",
                )
            )
            await uow.commit()

    async def close_account(self, user_id: UUID, *, reason: str) -> None:
        """Schedule the deletion and revoke access; the daily purge removes the data.

        Until then, logging in offers to restore the account.
        """
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            user.status = UserStatus.PENDING_DELETION
            user.deletion_requested_at = self.clock.now()
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            uow.audit(
                make_audit("user.deletion_requested", user_id=user_id, reason=reason)
            )
            await uow.commit()

"""Runtime limits: catalogue, overrides and per-user extensions (admin only).

Every change is audited in the transaction that makes it, and the provider's cache is
dropped after the commit, so the same process applies the change at once (other
processes within the cache time, 30 seconds).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.modules.admin.domain.limits import (
    ExtensionRecord,
    ExtensionTerms,
    LimitSpec,
    check_extension,
    check_value,
    editable_specs,
    overrides_from_rows,
    spec_of,
    stored_key,
)
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.settings import LimitsSettings
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.limits import LimitsProvider, apply_overrides
from app.shared.notifications import AuditDraft

AUDIT_LIMITS_CHANGED = "admin.limits_changed"
AUDIT_EXTENSION_SAVED = "admin.limit_extension_saved"
AUDIT_EXTENSION_DELETED = "admin.limit_extension_deleted"


class LimitUserNotFoundError(NotFoundError):
    """The student an extension is for does not exist."""

    code = "admin/limit-user-not-found"
    message_key = "admin-limit-user-not-found"


@dataclass(frozen=True, slots=True)
class LimitRow:
    """One editable limit: its spec, the value in force, the environment's value."""

    spec: LimitSpec
    value: int | None
    default: int | None
    overridden: bool


@dataclass(frozen=True, slots=True)
class ExtensionRow:
    """An extension with the student it is for and whether it applies today."""

    record: ExtensionRecord
    user: UserRef | None
    active: bool


class LimitAdmin:
    """Reads and changes the runtime limits and the per-user extensions."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        identity: IdentityDirectory,
        limits: LimitsProvider,
        base: LimitsSettings,
        today: Callable[[], date],
    ) -> None:
        """Keep the collaborators; `base` is the environment's limits."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.limits = limits
        self.base = base
        self.today = today

    async def catalogue(self, actor: Actor) -> list[LimitRow]:
        """Every editable limit with its value, default and override flag."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            overrides = overrides_from_rows(await uow.limit_store.read_overrides())
        effective = apply_overrides(self.base, overrides)
        return [
            LimitRow(
                spec=spec,
                value=getattr(effective, spec.key),
                default=getattr(self.base, spec.key),
                overridden=spec.key in overrides,
            )
            for spec in editable_specs()
        ]

    async def update(self, actor: Actor, changes: Mapping[str, Any]) -> list[LimitRow]:
        """Set (or with null reset) the given limits; the others keep their values."""
        actor.require(Role.ADMIN)
        cleaned = {
            key: check_value(spec_of(key), value) for key, value in changes.items()
        }
        async with self.uow_factory() as uow:
            stored = overrides_from_rows(await uow.limit_store.read_overrides())
            new_stored = dict(stored)
            for key, value in cleaned.items():
                if value is None:
                    new_stored.pop(key, None)
                else:
                    new_stored[key] = value
            before = apply_overrides(self.base, stored)
            after = apply_overrides(self.base, new_stored)
            diff = {
                key: {"old": getattr(before, key), "new": getattr(after, key)}
                for key in cleaned
                if getattr(before, key) != getattr(after, key)
            }
            upserts = {stored_key(k): v for k, v in cleaned.items() if v is not None}
            deletes = [
                stored_key(k) for k, v in cleaned.items() if v is None and k in stored
            ]
            if upserts or deletes:
                await uow.limit_store.write_overrides(
                    upserts, deletes, updated_by=actor.user_id
                )
            if diff:
                uow.audit(
                    AuditDraft(
                        type=AUDIT_LIMITS_CHANGED,
                        actor_id=actor.user_id,
                        metadata={"changes": diff},
                    )
                )
            await uow.commit()
        self.limits.invalidate()
        return await self.catalogue(actor)

    async def extensions(
        self, actor: Actor, *, user_id: UUID | None = None
    ) -> list[ExtensionRow]:
        """Every extension, or the one of a user, with the student's name."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            records = await uow.limit_store.read_extensions()
        if user_id is not None:
            records = [record for record in records if record.user_id == user_id]
        users = await self.identity.get_users([record.user_id for record in records])
        today = self.today()
        return [
            ExtensionRow(
                record=record,
                user=users.get(record.user_id),
                active=record.terms.expires_on is None
                or record.terms.expires_on >= today,
            )
            for record in records
        ]

    async def save_extension(
        self, actor: Actor, user_id: UUID, terms: ExtensionTerms
    ) -> ExtensionRow:
        """Create or replace the extension of a student."""
        actor.require(Role.ADMIN)
        checked = check_extension(terms, self.today())
        if await self.identity.get_user(user_id) is None:
            raise LimitUserNotFoundError(params={"user_id": str(user_id)})
        async with self.uow_factory() as uow:
            previous = await uow.limit_store.get_extension(user_id)
            await uow.limit_store.save_extension(
                user_id, checked, actor_id=actor.user_id
            )
            uow.audit(
                AuditDraft(
                    type=AUDIT_EXTENSION_SAVED,
                    actor_id=actor.user_id,
                    metadata={
                        "user_id": str(user_id),
                        "old": _terms_json(previous.terms) if previous else None,
                        "new": _terms_json(checked),
                    },
                )
            )
            await uow.commit()
        self.limits.invalidate()
        (row,) = await self.extensions(actor, user_id=user_id)
        return row

    async def delete_extension(self, actor: Actor, user_id: UUID) -> bool:
        """Remove the extension of a student; False when there was none."""
        actor.require(Role.ADMIN)
        async with self.uow_factory() as uow:
            previous = await uow.limit_store.get_extension(user_id)
            if previous is None:
                return False
            await uow.limit_store.delete_extension(user_id)
            uow.audit(
                AuditDraft(
                    type=AUDIT_EXTENSION_DELETED,
                    actor_id=actor.user_id,
                    metadata={
                        "user_id": str(user_id),
                        "old": _terms_json(previous.terms),
                    },
                )
            )
            await uow.commit()
        self.limits.invalidate()
        return True

    async def search_students(self, actor: Actor, query: str) -> list[UserRef]:
        """Students whose name or login matches the query (for the extension picker)."""
        actor.require(Role.ADMIN)
        return await self.identity.search_users(query, roles=(Role.STUDENT,), limit=20)


def _terms_json(terms: ExtensionTerms) -> dict[str, Any]:
    return {
        "multiplier": terms.multiplier,
        "values": dict(terms.values),
        "expires_on": terms.expires_on.isoformat() if terms.expires_on else None,
        "note": terms.note,
    }


__all__ = [
    "AUDIT_EXTENSION_DELETED",
    "AUDIT_EXTENSION_SAVED",
    "AUDIT_LIMITS_CHANGED",
    "ExtensionRow",
    "LimitAdmin",
    "LimitRow",
    "LimitUserNotFoundError",
]

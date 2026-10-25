"""PATCH /v1/id/me/preferences: merge a partial preferences document."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.load_user import require_user
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.identity import UserPreferences

from pydantic import ValidationError


@dataclass(frozen=True, slots=True)
class UpdatePreferences:
    """Validates the patch against UserPreferences, then merges it atomically."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor, patch: dict[str, Any]) -> UserPreferences:
        """Apply the patch for the caller."""
        return await self.for_user(actor.user_id, patch)

    async def for_user(self, user_id: UUID, patch: dict[str, Any]) -> UserPreferences:
        """Apply the patch for any user (used by IdentityCommands)."""
        unknown = set(patch) - set(UserPreferences.model_fields)
        if unknown:
            raise ValidationFailedError(params={"unknown": sorted(unknown)})
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            try:
                checked = UserPreferences.model_validate({**user.preferences, **patch})
            except ValidationError as exc:
                fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
                raise ValidationFailedError(params={"fields": fields}) from exc
            to_store = checked.model_dump(mode="json", include=set(patch))
            merged = await uow.users.merge_preferences(user_id, to_store)
            await uow.commit()
        return UserPreferences.model_validate(merged)

"""AccountRevoker port implementation, used by B2 (reclaim, deletion)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.errors import UserNotFoundError
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class AccountRevokerImpl:
    """Opens its own transaction and logs the user out everywhere."""

    uow_factory: UowFactory
    revoker: AccessRevoker

    async def revoke_everything(
        self, user_id: UUID, *, keep_telegram: bool = False
    ) -> None:
        """Bump the epoch; revoke Hydra sessions, sessions and connectors."""
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFoundError(params={"user_id": str(user_id)})
            await self.revoker.revoke_in(uow, user, keep_telegram=keep_telegram)
            await uow.commit()

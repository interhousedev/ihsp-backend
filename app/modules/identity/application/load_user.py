"""Load the user behind an actor inside a unit of work."""

from uuid import UUID

from app.modules.identity.domain.errors import UserNotFoundError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort


async def require_user(uow: IdentityUnitOfWorkPort, user_id: UUID) -> User:
    """Return the user or raise UserNotFoundError."""
    user = await uow.users.get(user_id)
    if user is None:
        raise UserNotFoundError(params={"user_id": str(user_id)})
    return user

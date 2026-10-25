"""Look up the user behind an activation link."""

from app.modules.identity.domain.errors import ActivationLinkInvalidError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock
from app.shared.ids import hash_token


async def user_for_token(uow: IdentityUnitOfWorkPort, token: str, clock: Clock) -> User:
    """Return the user, or raise ActivationLinkInvalidError (unknown or expired)."""
    user = await uow.users.get_by_activation_hash(hash_token(token))
    if (
        user is None
        or user.activation_expires_at is None
        or user.activation_expires_at <= clock.now()
    ):
        raise ActivationLinkInvalidError()
    return user

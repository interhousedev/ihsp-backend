"""Find the account a recovery request means, or None (callers stay neutral)."""

from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort


async def find_user_for_recovery(
    uow: IdentityUnitOfWorkPort, login_or_email: str, *, allow_admin: bool = False
) -> User | None:
    """Active user with a verified recovery email; Administration only if allowed."""
    value = login_or_email.strip()
    if not value:
        return None
    if "@" in value:
        user = await uow.users.get_by_recovery_email(value)
    else:
        user = await uow.users.get_by_login(value)
    if user is None or not user.is_active or not user.has_verified_email:
        return None
    if user.is_admin and not allow_admin:
        return None
    return user

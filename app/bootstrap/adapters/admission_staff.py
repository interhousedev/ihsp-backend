"""Admission's read-only view of users, for delegating staff assignments."""

from uuid import UUID

from app.modules.admission.domain.staff import StaffUser
from app.shared.contracts.identity import IdentityDirectory, UserStatus


class AdmissionStaffDirectoryAdapter:
    """Implements the admission `StaffDirectory` port over the identity directory."""

    def __init__(self, identity: IdentityDirectory) -> None:
        """Keep the identity directory."""
        self._identity = identity

    async def staff_user(self, user_id: UUID) -> StaffUser | None:
        """Return the user's roles and whether the account is active."""
        user = await self._identity.get_user(user_id)
        if user is None:
            return None
        return StaffUser(
            user_id=user.id,
            roles=frozenset(r.value for r in user.roles),
            active=user.status == UserStatus.ACTIVE,
        )

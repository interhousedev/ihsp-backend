"""Job identity.purge_deleted_users: remove personal data 30 days after deletion."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.domain.audit_event import USER_PURGED
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

RETENTION = timedelta(days=30)
BATCH = 500
PURGED_NAME = "Deleted"


def anonymize(user: User) -> None:
    """Drop everything that identifies the person; the row stays for the records."""
    user.first_name = PURGED_NAME
    user.last_name = ""
    user.middle_name = None
    user.login = f"deleted-{user.id.hex[-12:]}"
    user.password_hash = None
    user.recovery_email = None
    user.recovery_email_verified_at = None
    user.preferences = {}
    user.photo_file_id = None  # the file goes with the owner's other files
    user.emis_student_id = None
    user.emis_vault_ref = None
    user.emis_status = None
    user.otp_enabled = False
    user.otp_via_email = False
    user.clear_activation()
    user.clear_otp_reset()


@dataclass(frozen=True, slots=True)
class PurgeDeletedUsers:
    """Daily clean-up of accounts deleted more than 30 days ago (ID-29)."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self) -> int:
        """Return how many accounts were anonymized."""
        cutoff = self.clock.now() - RETENTION
        async with self.uow_factory() as uow:
            users = await uow.users.purgeable(cutoff, BATCH)
            for user in users:
                anonymize(user)
                await uow.users.save(user)
                uow.audit(make_audit(USER_PURGED, user_id=user.id))
            await uow.commit()
        return len(users)

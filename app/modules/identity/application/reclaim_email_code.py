"""Send the email confirmation code during reclaim (UF-ID-15 step 3)."""

from app.modules.identity.application.register_errors import RegistrationExpiredError
from app.modules.identity.application.register_models import PendingReclaim
from app.modules.identity.application.register_ports import PendingStore
from app.modules.identity.application.register_verification import EmailVerifier


class SendReclaimEmailCode:
    """Remember the new email of a pending reclaim and mail it a code."""

    def __init__(
        self, *, pending: PendingStore[PendingReclaim], verifier: EmailVerifier
    ) -> None:
        """Store the collaborators."""
        self._pending = pending
        self._verifier = verifier

    async def execute(self, *, reclaim_token: str, email: str) -> None:
        """Mail a code; the account's own current email is allowed."""
        pending = await self._pending.get(reclaim_token)
        if pending is None:
            raise RegistrationExpiredError()
        pending.email = await self._verifier.send(
            token=reclaim_token,
            email=email,
            except_user_id=pending.user_id,
            locale=pending.locale,
        )
        await self._pending.save(reclaim_token, pending)

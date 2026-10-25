"""Send the email confirmation code during registration (UF-ID-01 step 7)."""

from app.modules.identity.application.register_errors import RegistrationExpiredError
from app.modules.identity.application.register_models import PendingRegistration
from app.modules.identity.application.register_ports import PendingStore
from app.modules.identity.application.register_verification import EmailVerifier


class SendRegistrationEmailCode:
    """Remember the email of a pending registration and mail it a code."""

    def __init__(
        self, *, pending: PendingStore[PendingRegistration], verifier: EmailVerifier
    ) -> None:
        """Store the collaborators."""
        self._pending = pending
        self._verifier = verifier

    async def execute(self, *, registration_token: str, email: str) -> None:
        """Mail a code; a new request replaces the previous code and email."""
        pending = await self._pending.get(registration_token)
        if pending is None:
            raise RegistrationExpiredError()
        pending.email = await self._verifier.send(
            token=registration_token,
            email=email,
            except_user_id=pending.import_user_id,
            locale=pending.locale,
        )
        await self._pending.save(registration_token, pending)

"""One-time activation and password-reset links for staff accounts (ID-10)."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.ports.email_sender import EmailSender
from app.shared.clock import Clock
from app.shared.ids import hash_token, random_token

import structlog

log = structlog.get_logger(__name__)

LINK_HOURS = 72


@dataclass(frozen=True, slots=True)
class ActivationLinks:
    """Issues links (hash stored on the user) and emails them."""

    clock: Clock
    email: EmailSender
    id_app_url: str

    def issue(self, user: User, purpose: ActivationPurpose) -> str:
        """Set a fresh token on the user (caller saves) and return the URL."""
        token = random_token(32)
        expires = self.clock.now() + timedelta(hours=LINK_HOURS)
        user.set_activation(hash_token(token), expires, purpose)
        return f"{self.id_app_url.rstrip('/')}/activate/?token={token}"

    async def send(self, user: User, url: str) -> None:
        """Email the link to the user's address; a relay failure is only logged."""
        if not user.recovery_email:
            return
        params = {
            "name": user.full_name,
            "login": user.login or "",
            "link": url,
            "hours": LINK_HOURS,
        }
        try:
            await self.email.send(
                user.recovery_email, "activation", params, user.locale
            )
        except EmailDeliveryError:
            log.warning("activation_email_failed", user_id=str(user.id))

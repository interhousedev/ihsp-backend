"""GET /v1/id/activation/{token}: whose account the link activates."""

from dataclasses import dataclass

from app.modules.identity.application.activation_token import user_for_token
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class ActivationInfoResult:
    """What the activation page shows before the form."""

    first_name: str
    last_name: str
    login: str | None
    requires_otp: bool


@dataclass(frozen=True, slots=True)
class ActivationInfo:
    """Describes a valid activation or reset link."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self, token: str) -> ActivationInfoResult:
        """Return the account data or raise ActivationLinkInvalidError."""
        async with self.uow_factory() as uow:
            user = await user_for_token(uow, token, self.clock)
        return ActivationInfoResult(
            first_name=user.first_name,
            last_name=user.last_name,
            login=user.login,
            requires_otp=user.is_admin,
        )

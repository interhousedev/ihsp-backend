"""GET /v1/id/activation/{token}: whose account the link activates."""

from app.interfaces.http.v1.id.activation.schemas import ActivationInfoResponse
from app.interfaces.http.v1.id.dependencies import AuthDep


async def get_activation(token: str, auth: AuthDep) -> ActivationInfoResponse:
    """Name, login and whether OTP setup follows."""
    return ActivationInfoResponse.of(await auth.activation_info.execute(token))

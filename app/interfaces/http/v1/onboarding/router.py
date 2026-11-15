"""Routes of the onboarding wizard."""

from app.interfaces.http.v1.onboarding.handlers import onboarding
from app.interfaces.http.v1.onboarding.schemas import OnboardingOut, RefreshEmisOut

from fastapi import APIRouter

router = APIRouter(tags=["onboarding"])

router.add_api_route(
    "/v1/me/onboarding",
    onboarding.get_onboarding,
    methods=["GET"],
    response_model=OnboardingOut,
)
router.add_api_route(
    "/v1/me/onboarding/certificates/done",
    onboarding.certificates_done,
    methods=["POST"],
    response_model=OnboardingOut,
)
router.add_api_route(
    "/v1/me/onboarding/certificates/refresh-emis",
    onboarding.refresh_emis,
    methods=["POST"],
    response_model=RefreshEmisOut,
)

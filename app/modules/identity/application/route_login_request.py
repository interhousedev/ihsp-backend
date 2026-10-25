"""GET /v1/oauth/flow/login: Hydra's login URL; the page is skipped when possible."""

from dataclasses import dataclass

from app.modules.identity.application.flow_pages import (
    page_url,
    restart_login_url,
    used_target,
)
from app.modules.identity.application.get_login_info import GetLoginInfo
from app.modules.identity.domain.errors import ChallengeUsedError
from app.modules.identity.ports.hydra_gateway import HydraGateway

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RouteLoginRequest:
    """Decides, without rendering anything, where a login challenge goes."""

    hydra: HydraGateway
    login_info: GetLoginInfo
    id_url: str

    async def execute(self, challenge: str) -> str:
        """Return the URL to redirect to: Hydra again (SSO) or the login form."""
        form = page_url(self.id_url, "/login/", "login_challenge", challenge)
        try:
            request = await self.hydra.get_login_request(challenge)
            info = await self.login_info.describe(request)
        except ChallengeUsedError as exc:
            return used_target(exc, form)
        except Exception:  # the form shows the failure and offers a retry
            log.exception("flow_login_failed")
            return form
        if info.redirect_to:
            return info.redirect_to
        if request.skip and request.request_url:
            # Hydra has a session we refuse (other role, old second factor, blocked
            # user): restart so that the user logs in once, whoever they are.
            return restart_login_url(request.request_url)
        return page_url(
            self.id_url,
            "/login/",
            "login_challenge",
            challenge,
            client_id=info.client_id,
            client_name=info.client_name,
        )

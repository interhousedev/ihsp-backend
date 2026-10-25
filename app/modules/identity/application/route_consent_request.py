"""GET /v1/oauth/flow/consent: Hydra's consent URL. Our own apps never see a page."""

from dataclasses import dataclass

from app.modules.identity.application.auto_accept_consent import AutoAcceptConsent
from app.modules.identity.application.flow_pages import page_url, used_target
from app.modules.identity.domain.client_policy import is_first_party
from app.modules.identity.domain.errors import ChallengeUsedError
from app.modules.identity.ports.hydra_gateway import HydraGateway

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RouteConsentRequest:
    """First-party clients are accepted here; MCP clients get the consent page."""

    hydra: HydraGateway
    auto_accept: AutoAcceptConsent
    id_url: str

    async def execute(self, challenge: str) -> str:
        """Return the URL to redirect to: Hydra again, or the consent page."""
        page = page_url(self.id_url, "/consent/", "consent_challenge", challenge)
        try:
            request = await self.hydra.get_consent_request(challenge)
            if is_first_party(request.client.client_id):
                return await self.auto_accept.execute(request)
        except ChallengeUsedError as exc:
            return used_target(exc, page)
        except Exception:  # the page shows the failure and offers a retry
            log.exception("flow_consent_failed")
        return page

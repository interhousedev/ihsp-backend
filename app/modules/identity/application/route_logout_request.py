"""GET /v1/oauth/flow/logout: Hydra's logout URL. Accept at once and continue."""

from dataclasses import dataclass

from app.modules.identity.application.accept_logout import AcceptLogout
from app.modules.identity.application.flow_pages import page_url, used_target
from app.modules.identity.domain.errors import ChallengeUsedError

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RouteLogoutRequest:
    """Ends our session and sends the browser on to Hydra's end-session step."""

    accept_logout: AcceptLogout
    id_url: str

    async def execute(self, challenge: str) -> str:
        """Return the URL to redirect to: Hydra again, or the page after a failure."""
        page = page_url(self.id_url, "/logout/", "logout_challenge", challenge)
        try:
            return await self.accept_logout.execute(challenge)
        except ChallengeUsedError as exc:
            return used_target(exc, page)
        except Exception:  # the page shows the failure and offers a retry
            log.exception("flow_logout_failed")
            return page

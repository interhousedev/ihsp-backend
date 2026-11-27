"""Public club directory and the contact form relayed to the club owner."""

from uuid import UUID

from app.modules.activities.application.common import load_club
from app.modules.activities.domain.club import Club, ClubStatus
from app.modules.activities.domain.contact import (
    CaptchaFailedError,
    ContactRequest,
    ContactUnavailableError,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.ports.bundle import Ports

CLUB_LIMIT = 3
IP_LIMIT = 5
WINDOW = 3600


def _shown(club: Club) -> bool:
    return club.status == ClubStatus.ACTIVE and club.visibility_public


class PublicService:
    """What anonymous visitors see and send."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def list_clubs(self) -> list[Club]:
        """Active public clubs."""
        return [c for c in await self._p.clubs.list_all() if _shown(c)]

    async def get_club(self, slug: str) -> Club:
        """One active public club or 404."""
        club = await self._p.clubs.get_by_slug(slug)
        if club is None or not _shown(club):
            raise ActivitiesNotFoundError()
        return club

    async def get_active_club(self, club_id: UUID) -> Club:
        """One active club by id or 404 (its logo is public info)."""
        club = await self._p.clubs.get(club_id)
        if club is None or club.status != ClubStatus.ACTIVE:
            raise ActivitiesNotFoundError()
        return club

    async def contact_open(self, club: Club) -> bool:
        """Whether the form works: switched on and the owner can get Telegram."""
        if not club.contact_enabled:
            return False
        owner_id = (await load_club(self._p, club.id)).owner_id
        return owner_id is not None and await self._p.contact_relay.reachable(owner_id)

    async def submit_contact(
        self,
        slug: str,
        *,
        name: str,
        email: str,
        message: str,
        captcha_token: str,
        honeypot: str,
        ip: str,
    ) -> None:
        """Check a visitor's message and send it to the owner's Telegram only."""
        p = self._p
        club = await load_club(p, (await self.get_club(slug)).id)
        request = ContactRequest.create(
            club=club,
            name=name,
            email=email,
            body=message,
            ip=ip,
            salt=p.ip_salt,
            honeypot=honeypot,
        )
        if request.is_spam:
            return
        if not await p.captcha.verify(captcha_token, ip):
            raise CaptchaFailedError()
        await p.limiter.hit(
            f"club-contact:{club.id}:{request.ip_hash}",
            limit=CLUB_LIMIT,
            window_seconds=WINDOW,
        )
        await p.limiter.hit(
            f"club-contact-ip:{request.ip_hash}", limit=IP_LIMIT, window_seconds=WINDOW
        )
        delivered = club.owner_id is not None and await p.contact_relay.deliver(
            club.owner_id,
            club_slug=club.slug,
            name=request.name,
            email=request.email,
            body=request.body,
        )
        if not delivered:
            raise ContactUnavailableError()

"""Club <-> course links: one side asks, the other side confirms."""

from uuid import UUID

from app.modules.activities.application.common import load_club
from app.modules.activities.domain import course_link as rules
from app.modules.activities.domain.course_link import ClubCourseLink
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor


class ClubCourseService:
    """Links a club to a course; both scopes are re-read on every step."""

    def __init__(self, p: Ports) -> None:
        """Keep the ports."""
        self._p = p

    async def _sides(
        self, actor: Actor, club_id: UUID, course_id: UUID
    ) -> tuple[bool, bool]:
        club = await load_club(self._p, club_id)
        if not await self._p.courses.exists(course_id):
            raise ActivitiesNotFoundError()
        return (
            club.owner_id == actor.user_id,
            await self._p.courses.is_staff(course_id, actor.user_id),
        )

    async def _open_link(self, club_id: UUID, course_id: UUID) -> ClubCourseLink:
        for link in await self._p.links.list_pair(club_id, course_id):
            if link.status in ("pending", "active"):
                return link
        raise ActivitiesNotFoundError()

    async def request(
        self, actor: Actor, club_id: UUID, course_id: UUID
    ) -> ClubCourseLink:
        """Ask for a link; it is active at once only when the actor holds both sides."""
        club_side, course_side = await self._sides(actor, club_id, course_id)
        link = rules.request_link(
            club_id,
            course_id,
            actor.user_id,
            is_club_owner=club_side,
            is_course_owner_or_teacher=course_side,
            existing=await self._p.links.list_pair(club_id, course_id),
            now=self._p.clock.now(),
        )
        await self._p.links.add(link)
        return link

    async def confirm(
        self, actor: Actor, club_id: UUID, course_id: UUID
    ) -> ClubCourseLink:
        """The other side accepts the pending request."""
        club_side, course_side = await self._sides(actor, club_id, course_id)
        link = await self._open_link(club_id, course_id)
        rules.confirm(
            link,
            actor.user_id,
            is_club_owner=club_side,
            is_course_owner_or_teacher=course_side,
            now=self._p.clock.now(),
        )
        await self._p.links.save(link)
        return link

    async def unlink(self, actor: Actor, club_id: UUID, course_id: UUID) -> None:
        """Either side ends the link or declines a pending request."""
        club_side, course_side = await self._sides(actor, club_id, course_id)
        link = await self._open_link(club_id, course_id)
        rules.unlink(
            link, is_club_owner=club_side, is_course_owner_or_teacher=course_side
        )
        await self._p.links.save(link)

    async def for_club(self, actor: Actor, club_id: UUID) -> list[ClubCourseLink]:
        """Active links of the club; the owner also sees pending ones."""
        club = await load_club(self._p, club_id)
        own = club.owner_id == actor.user_id
        return [
            x
            for x in await self._p.links.list_for_club(club_id)
            if x.status == "active" or own
        ]

    async def for_course(self, actor: Actor, course_id: UUID) -> list[ClubCourseLink]:
        """Active links of the course; its staff also see pending ones."""
        own = await self._p.courses.is_staff(course_id, actor.user_id)
        return [
            x
            for x in await self._p.links.list_for_course(course_id)
            if x.status == "active" or own
        ]

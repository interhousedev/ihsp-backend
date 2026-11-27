"""Builds the activities services from their ports."""

from dataclasses import dataclass, replace
from typing import Any

from app.modules.activities.application.announcements import AnnouncementService
from app.modules.activities.application.clubs import ClubService
from app.modules.activities.application.events import EventService
from app.modules.activities.application.memberships import MembershipService
from app.modules.activities.application.ownership import OwnershipService
from app.modules.activities.application.public import PublicService
from app.modules.activities.application.ratings import RatingService
from app.modules.activities.ports.bundle import Ports


@dataclass(frozen=True, slots=True)
class ActivitiesServices:
    """Every service of the module."""

    clubs: ClubService
    memberships: MembershipService
    ownership: OwnershipService
    events: EventService
    ratings: RatingService
    announcements: AnnouncementService
    public: PublicService


def build(deps: Ports, overrides: dict[str, Any] | None = None) -> ActivitiesServices:
    """Services over `deps`; `overrides` replaces whole services by field name."""
    services = ActivitiesServices(
        clubs=ClubService(deps),
        memberships=MembershipService(deps),
        ownership=OwnershipService(deps),
        events=EventService(deps),
        ratings=RatingService(deps),
        announcements=AnnouncementService(deps),
        public=PublicService(deps),
    )
    return replace(services, **overrides) if overrides else services

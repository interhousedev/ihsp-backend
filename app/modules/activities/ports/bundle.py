"""Every port the application services use, handed over as one object."""

from dataclasses import dataclass

from app.modules.activities.ports.gateways import (
    AuditLog,
    Captcha,
    ContactRelay,
    Notifier,
    OpportunityCatalog,
    RateLimiter,
    UserDirectory,
)
from app.modules.activities.ports.repositories import (
    AnnouncementRepository,
    ClubRepository,
    CourseLinkRepository,
    DraftRepository,
    EventRepository,
    MembershipRepository,
    PlannerRepository,
    PointsRepository,
    RatingRepository,
    TeamRepository,
    TransferRepository,
)
from app.shared.clock import Clock
from app.shared.contracts.club_courses import CourseDirectory


@dataclass(frozen=True, slots=True)
class Ports:
    """Repositories, gateways and settings shared by the services."""

    clubs: ClubRepository
    members: MembershipRepository
    transfers: TransferRepository
    events: EventRepository
    ratings: RatingRepository
    announcements: AnnouncementRepository
    planner: PlannerRepository
    drafts: DraftRepository
    points: PointsRepository
    team: TeamRepository
    links: CourseLinkRepository
    notifier: Notifier
    users: UserDirectory
    courses: CourseDirectory
    captcha: Captcha
    contact_relay: ContactRelay
    limiter: RateLimiter
    audit: AuditLog
    catalog: OpportunityCatalog
    clock: Clock
    secret: str
    ip_salt: str

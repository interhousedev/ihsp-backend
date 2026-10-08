"""The composition use cases an app serves."""

from dataclasses import dataclass

from app.interfaces.http.v1.composition.application.build_admin_dashboard import (
    BuildAdminDashboard,
)
from app.interfaces.http.v1.composition.application.build_alerts import BuildAlerts
from app.interfaces.http.v1.composition.application.build_calendar_feed import (
    BuildCalendarFeed,
)
from app.interfaces.http.v1.composition.application.build_group_stats import (
    BuildGroupStats,
)
from app.interfaces.http.v1.composition.application.build_student_360 import (
    BuildStudent360,
)
from app.interfaces.http.v1.composition.application.build_teacher_profile import (
    BuildTeacherProfile,
)
from app.interfaces.http.v1.composition.application.issue_calendar_token import (
    IssueCalendarToken,
)
from app.interfaces.http.v1.composition.application.search_all import SearchAll


@dataclass(frozen=True, slots=True)
class Composition:
    """Use cases that compose several modules; attribute name = use case file name."""

    build_alerts: BuildAlerts
    search_all: SearchAll
    issue_calendar_token: IssueCalendarToken
    build_calendar_feed: BuildCalendarFeed
    build_admin_dashboard: BuildAdminDashboard
    build_group_stats: BuildGroupStats
    build_student_360: BuildStudent360
    build_teacher_profile: BuildTeacherProfile

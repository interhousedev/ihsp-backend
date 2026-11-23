"""Personal-data specification of the lms module (export and erasure)."""

from app.modules.lms.infrastructure.orm.ai_review import AiReviewSession
from app.modules.lms.infrastructure.orm.badge import BadgeAward
from app.modules.lms.infrastructure.orm.course_staff import CourseStaff
from app.modules.lms.infrastructure.orm.engagement import (
    EngagementProfile,
    ReviewItem,
    XpEvent,
)
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.infrastructure.orm.step_state import StepState
from app.modules.lms.infrastructure.orm.test_attempt import TestAttempt
from app.shared.personal_data import (
    ParentLink,
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N, R = Treatment.ERASE, Treatment.NULLIFY, Treatment.RETAIN
_ = ParentLink

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(CourseStaff, R, owner="user_id", note="course record"),
    PersonalTable(Enrollment, R, owner="user_id", note="course record"),
    PersonalTable(StepState, R, owner="user_id", note="course record"),
    PersonalTable(TestAttempt, R, owner="user_id", note="course record"),
    PersonalTable(AiReviewSession, R, owner="user_id", note="course record"),
    PersonalTable(BadgeAward, E, owner="user_id", note="engagement"),
    PersonalTable(EngagementProfile, E, owner="user_id", note="engagement"),
    PersonalTable(ReviewItem, E, owner="user_id", note="engagement"),
    PersonalTable(XpEvent, E, owner="user_id", note="engagement"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)

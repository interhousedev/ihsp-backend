"""Who may see a course landing page and who may enrol (pure rules)."""

from datetime import datetime

from app.modules.lms.domain.learning.entities import LearningCourse


def landing_visible(
    course: LearningCourse,
    *,
    enrolled: bool,
    is_staff: bool,
    previewing: bool,
) -> bool:
    """Return True if the viewer may open the landing page.

    Authors previewing (``previewing`` is only True for people who can edit) see
    drafts and unpublished courses. Members and staff always see their course.
    Everyone else needs a published, active, public course whose audience scope
    is not `group` (group membership is not checked here, so those courses stay
    hidden from non-members).
    """
    if previewing or enrolled or is_staff:
        return True
    return (
        course.is_open_for_students
        and course.publish_state == "published"
        and course.visibility == "public"
        and course.audience_scope != "group"
    )


def can_enrol(course: LearningCourse, *, enrolled: bool, now: datetime) -> bool:
    """Return True if the viewer may press "Enrol" now."""
    if enrolled or not course.is_open_for_students or course.visibility != "public":
        return False
    if course.audience_scope == "group" or not course.enrolment_open:
        return False
    starts, ends = course.enrolment_starts_at, course.enrolment_ends_at
    return (starts is None or now >= starts) and (ends is None or now < ends)

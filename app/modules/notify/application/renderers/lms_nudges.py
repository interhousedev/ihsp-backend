"""Opt-in LMS nudges: review due, streak at risk and a class quest ending soon."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LmsReviewDueRenderer(DescribedRenderer):
    """Review questions are due; the button opens the LMS review page."""

    notification_type = NotificationType.LMS_REVIEW_DUE
    link_button_key = "notify-btn-open-review"


class LmsStreakAtRiskRenderer(DescribedRenderer):
    """No activity yet today; the button opens the learner's LMS page."""

    notification_type = NotificationType.LMS_STREAK_AT_RISK
    link_button_key = "notify-btn-open-lms"


class LmsDeadlineSoonRenderer(DescribedRenderer):
    """A class quest ends soon; the button opens the learner's LMS page."""

    notification_type = NotificationType.LMS_DEADLINE_SOON
    link_button_key = "notify-btn-open-lms"

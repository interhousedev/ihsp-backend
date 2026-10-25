"""JSON-shaped pages the local ports return (types of the API contract)."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.composition.application.views import (
    lesson_item,
    person_ref,
)
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from tests.composition.fakes import make_lesson

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def lesson_json(**kwargs: Any) -> dict[str, Any]:
    """A `LessonItem` built from a canned lesson."""
    return lesson_item(make_lesson(**kwargs), {})


def student_profile(user: UserRef) -> dict[str, Any]:
    """A `StudentProfile`."""
    return {
        "user_id": user.id,
        "login": user.login,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "mailbox": f"{user.login}@mail.ihsu.uz",
        "group": {"id": new_id(), "name": "2TN2"},
        "subgroup": 1,
        "curator": {"id": new_id(), "first_name": "Nodira", "last_name": "Aliyeva"},
        "head_student": None,
        "current_semester": 3,
        "emis_status": "active",
        "synced_at": NOW,
    }


def semester_grades() -> dict[str, Any]:
    """A `SemesterGrades`."""
    subject = {"id": new_id(), "name": "Mathematics", "short_name": "Math"}
    return {
        "semester": 3,
        "gpa": 4.2,
        "synced_at": NOW,
        "rows": [
            {
                "subject": subject,
                "lesson_avg": 4.5,
                "midterm_avg": None,
                "final_avg": None,
                "semester_mark": 4.5,
                "emis_rating": 88,
                "marks_count": 3,
            }
        ],
    }


def student_attendance() -> dict[str, Any]:
    """A `StudentAttendance`; the keys `from` and `to` are the JSON names."""
    subject = {"id": new_id(), "name": "Mathematics", "short_name": "Math"}
    return {
        "from": "2026-09-02",
        "to": "2026-12-30",
        "summary": [
            {
                "subject": subject,
                "absences": 1,
                "excused": 0,
                "lessons": 8,
                "rate": 0.125,
            }
        ],
        "days": [{"date": "2026-09-15", "absences": 1}],
        "missed": [{"lesson": lesson_json(), "excused": False}],
        "not_taken": 2,
    }


def admin_user(user: UserRef) -> dict[str, Any]:
    """An `AdminUser`."""
    return {
        "id": user.id,
        "login": user.login,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "middle_name": None,
        "roles": sorted(role.value for role in user.roles),
        "status": user.status.value,
        "emis_status": user.emis_status,
        "recovery_email": None,
        "mail_suspended": False,
        "created_at": NOW - dt.timedelta(days=30),
        "last_login_at": NOW - dt.timedelta(hours=2),
    }


def account_detail(user: UserRef, *, actor_id: UUID | None = None) -> dict[str, Any]:
    """An `AdminUserDetail` with one Telegram account, session and audit event."""
    actor = None
    if actor_id is not None:
        actor = {"id": actor_id, "first_name": "Root", "last_name": "Admin"}
    return {
        **admin_user(user),
        "telegram": [
            {
                "telegram_user_id": 424242,
                "username": "aziza",
                "otp_delivery": True,
                "blocked": False,
                "linked_at": NOW - dt.timedelta(days=20),
            }
        ],
        "sessions": [
            {
                "id": new_id(),
                "ip": "10.0.0.7",
                "user_agent": "Firefox",
                "amr": ["pwd"],
                "last_seen_at": NOW,
                "current": False,
            }
        ],
        "recent_audit": [
            {
                "id": new_id(),
                "type": "student.viewed",
                "ip": "10.0.0.9",
                "user_agent": "Chrome",
                "actor": actor,
                "created_at": NOW,
                "metadata": {},
            }
        ],
    }


def group_item() -> dict[str, Any]:
    """A `GroupItem`."""
    return {
        "id": new_id(),
        "name": "2TN2",
        "slug": "2tn2",
        "current_semester": 3,
        "status": "active",
        "students_count": 20,
        "subgroups_assigned": 18,
        "unregistered_count": 1,
        "curator": None,
        "head_student": None,
    }


def person(user: UserRef) -> dict[str, Any]:
    """A `PersonRef`."""
    return person_ref(user)

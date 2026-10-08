"""Adapters of the composition endpoints: one per port of `composition/ports.py`.

```python
ports = build_composition_ports(container)
composition = composition_from_container(container, ports)
```

Each adapter runs the provider module's use cases and returns the JSON-shaped dicts
that the port documents.
"""

from app.bootstrap.adapters.composition.account_views import AccountViewsAdapter
from app.bootstrap.adapters.composition.attendance_stats import AttendanceStatsAdapter
from app.bootstrap.adapters.composition.broadcast_views import BroadcastViewsAdapter
from app.bootstrap.adapters.composition.calendar_token_store import (
    CalendarTokenStoreAdapter,
)
from app.bootstrap.adapters.composition.files_views import FilesViewsAdapter
from app.bootstrap.adapters.composition.schedule_overview import ScheduleOverviewAdapter
from app.bootstrap.adapters.composition.student_views import StudentViewsAdapter
from app.bootstrap.adapters.composition.sync_views import SyncViewsAdapter
from app.bootstrap.adapters.composition.teacher_views import TeacherViewsAdapter
from app.bootstrap.container import Container
from app.interfaces.http.v1.composition.ports import CompositionPorts

__all__ = [
    "AccountViewsAdapter",
    "AttendanceStatsAdapter",
    "BroadcastViewsAdapter",
    "CalendarTokenStoreAdapter",
    "FilesViewsAdapter",
    "ScheduleOverviewAdapter",
    "StudentViewsAdapter",
    "SyncViewsAdapter",
    "TeacherViewsAdapter",
    "build_composition_ports",
]


def _built[T](module: T | None, name: str) -> T:
    """Return the module services or fail clearly when this process lacks them."""
    if module is None:
        raise RuntimeError(
            f"The composition endpoints need the '{name}' module, which this "
            "process did not build"
        )
    return module


def build_composition_ports(container: Container) -> CompositionPorts:
    """Implement every composition port over the module services of the container."""
    academic = _built(container.academic, "academic")
    schedule, classwork, marks = academic.schedule, academic.classwork, academic.marks
    files = _built(container.files, "files")
    identity = _built(container.identity, "identity")
    admin = _built(container.admin, "admin")
    return CompositionPorts(
        files=FilesViewsAdapter(files.list_my_files, files.public),
        sync=SyncViewsAdapter(marks.get_sync_failures, marks.list_sync_runs),
        calendar_tokens=CalendarTokenStoreAdapter(
            schedule.rotate_calendar_token, schedule.user_for_calendar_token
        ),
        schedule_overview=ScheduleOverviewAdapter(
            schedule.current_term, schedule.list_lessons, schedule.list_groups
        ),
        attendance_stats=AttendanceStatsAdapter(classwork.attendance_report),
        students=StudentViewsAdapter(
            schedule.get_student_profile,
            schedule.get_student_timetable,
            marks.get_semester_grades,
            classwork.student_attendance,
        ),
        teachers=TeacherViewsAdapter(
            schedule.get_staff_timetable,
            classwork.missing_attendance,
            schedule.list_curated_groups,
        ),
        accounts=AccountViewsAdapter(identity.auth.get_user_detail),
        broadcasts=BroadcastViewsAdapter(admin.list_broadcasts),
    )

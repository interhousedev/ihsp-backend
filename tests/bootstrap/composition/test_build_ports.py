"""`build_composition_ports`: every port is implemented, and gaps are reported."""

from types import SimpleNamespace
from typing import Any

from app.bootstrap.adapters.composition import (
    AccountViewsAdapter,
    AttendanceStatsAdapter,
    BroadcastViewsAdapter,
    CalendarTokenStoreAdapter,
    FilesViewsAdapter,
    ScheduleOverviewAdapter,
    StudentViewsAdapter,
    SyncViewsAdapter,
    TeacherViewsAdapter,
    build_composition_ports,
)
from app.interfaces.http.v1.composition.ports import CompositionPorts
from tests.bootstrap.composition.fakes import FakeFilesApi, FakeUseCase

import pytest


def make_container(**missing: bool) -> Any:
    """A container of namespaces whose attributes are fake use cases."""
    uc = FakeUseCase
    schedule = SimpleNamespace(
        rotate_calendar_token=uc(),
        user_for_calendar_token=uc(),
        current_term=uc(),
        list_lessons=uc(),
        list_groups=uc(),
        get_student_profile=uc(),
        get_student_timetable=uc(),
        get_staff_timetable=uc(),
        list_curated_groups=uc(),
    )
    classwork = SimpleNamespace(
        attendance_report=uc(), student_attendance=uc(), missing_attendance=uc()
    )
    marks = SimpleNamespace(
        get_sync_failures=uc(), list_sync_runs=uc(), get_semester_grades=uc()
    )
    modules = {
        "academic": SimpleNamespace(
            schedule=schedule, classwork=classwork, marks=marks
        ),
        "files": SimpleNamespace(list_my_files=uc(), public=FakeFilesApi()),
        "identity": SimpleNamespace(auth=SimpleNamespace(get_user_detail=uc())),
        "admin": SimpleNamespace(list_broadcasts=uc()),
        "notebooks": SimpleNamespace(public=object()),
        "library": SimpleNamespace(catalogue=SimpleNamespace(list_items=uc())),
    }
    for name in missing:
        modules[name] = None  # type: ignore[assignment]
    return SimpleNamespace(**modules)


def test_every_port_gets_its_adapter() -> None:
    """The bundle holds one adapter per port, wired to the module services."""
    ports = build_composition_ports(make_container())

    assert isinstance(ports, CompositionPorts)
    assert isinstance(ports.files, FilesViewsAdapter)
    assert isinstance(ports.sync, SyncViewsAdapter)
    assert isinstance(ports.calendar_tokens, CalendarTokenStoreAdapter)
    assert isinstance(ports.schedule_overview, ScheduleOverviewAdapter)
    assert isinstance(ports.attendance_stats, AttendanceStatsAdapter)
    assert isinstance(ports.students, StudentViewsAdapter)
    assert isinstance(ports.teachers, TeacherViewsAdapter)
    assert isinstance(ports.accounts, AccountViewsAdapter)
    assert isinstance(ports.broadcasts, BroadcastViewsAdapter)


@pytest.mark.parametrize("module", ["academic", "files", "identity", "admin"])
def test_a_module_the_process_did_not_build_is_named_in_the_error(module: str) -> None:
    """A process without a provider module fails at startup with a clear message."""
    with pytest.raises(RuntimeError, match=f"'{module}' module"):
        build_composition_ports(make_container(**{module: True}))

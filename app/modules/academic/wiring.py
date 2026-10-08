"""Assembly of the academic module: schedule, classwork and marks (task I1)."""

from dataclasses import dataclass
from typing import Any

from app.modules.academic.wiring_classwork import ClassworkServices, build_classwork
from app.modules.academic.wiring_marks import MarksServices, build_marks
from app.modules.academic.wiring_schedule import ScheduleServices, build_schedule

__all__ = [
    "AcademicModule",
    "ClassworkServices",
    "MarksServices",
    "ScheduleServices",
    "build_classwork",
    "build_marks",
    "build_schedule",
]


_NOT_BUILT: Any = None  # parts a process does not build stay None


@dataclass(slots=True)
class AcademicModule:
    """`container.academic`: the three parts share one schema and are built in turn.

    The schedule comes first (identity and files depend on it); classwork and marks
    need the links module, so the composition root builds them later; processes that
    do not need them (identity, mail) keep them None.
    """

    schedule: ScheduleServices
    classwork: ClassworkServices = _NOT_BUILT
    marks: MarksServices = _NOT_BUILT

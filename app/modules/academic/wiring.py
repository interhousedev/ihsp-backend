"""Assembly of the academic module: schedule, classwork and marks (task I1)."""

from dataclasses import dataclass
from typing import Any

from app.modules.academic.application.excuses.excuse_status import ExcuseStatusQuery
from app.modules.academic.infrastructure.curriculum_topics.refresher import (
    RefreshCurriculumTopics,
)
from app.modules.academic.wiring_assessments import (
    AssessmentServices,
    build_assessments,
)
from app.modules.academic.wiring_classwork import ClassworkServices, build_classwork
from app.modules.academic.wiring_day_blocks import DayBlockServices, build_day_blocks
from app.modules.academic.wiring_emis_import import (
    EmisImportServices,
    build_emis_import,
)
from app.modules.academic.wiring_excuses import ExcuseServices, build_excuses
from app.modules.academic.wiring_marks import MarksServices, build_marks
from app.modules.academic.wiring_schedule import ScheduleServices, build_schedule
from app.modules.academic.wiring_teaching import TeachingServices, build_teaching
from app.modules.ai.domain.requests import AiRequestSpec

# AI requests this module declares; the AI module publishes them at startup.
AI_REQUESTS: tuple[AiRequestSpec, ...] = ()

__all__ = [
    "AcademicModule",
    "AssessmentServices",
    "ClassworkServices",
    "DayBlockServices",
    "EmisImportServices",
    "ExcuseServices",
    "MarksServices",
    "ScheduleServices",
    "TeachingServices",
    "build_assessments",
    "build_classwork",
    "build_day_blocks",
    "build_emis_import",
    "build_excuses",
    "build_marks",
    "build_schedule",
    "build_teaching",
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
    emis_import: EmisImportServices = _NOT_BUILT
    assessments: AssessmentServices = _NOT_BUILT
    teaching: TeachingServices = _NOT_BUILT
    excuses: ExcuseServices = _NOT_BUILT
    day_blocks: DayBlockServices = _NOT_BUILT
    curriculum_topics: RefreshCurriculumTopics = _NOT_BUILT

    @property
    def excuse_status(self) -> ExcuseStatusQuery:
        """The cross-module excuse reader (gate and mini app)."""
        return self.excuses.status

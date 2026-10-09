"""Wiring of what the schedule imports from EMIS: bells, timetables, lessons."""

from dataclasses import dataclass

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.generate_lessons import GenerateLessons
from app.modules.academic.application.schedule.ports.lesson_urls import (
    LessonUrlImporter,
)
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.sync_class_hours import SyncClassHours
from app.modules.academic.application.schedule.sync_group_timetable import (
    SyncGroupTimetable,
)
from app.modules.academic.infrastructure.schedule.room_page_cache import (
    RedisRoomPageCache,
)
from app.modules.academic.wiring_schedule import (
    ScheduleServices,
    sql_schedule_uow_factory,
)
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.identity import IdentityCommands
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class EmisImportServices:
    """The EMIS import use cases, behind two tasks and the 20:00 sync run."""

    sync_class_hours: SyncClassHours
    sync_group_timetable: SyncGroupTimetable


def assemble_emis_import(
    *,
    uow_factory: UowFactory,
    emis: EmisSource,
    identity_commands: IdentityCommands,
    generate: GenerateLessons,
    urls: LessonUrlImporter,
    cache: RoomPageCache,
    kicker: TaskKicker,
    clock: Clock,
    import_topics: bool = False,
) -> EmisImportServices:
    """Connect the use cases to the given ports (real or fake)."""
    sync_class_hours = SyncClassHours(
        uow_factory=uow_factory, emis=emis, generate=generate, clock=clock
    )
    return EmisImportServices(
        sync_class_hours=sync_class_hours,
        sync_group_timetable=SyncGroupTimetable(
            uow_factory=uow_factory,
            emis=emis,
            identity_commands=identity_commands,
            sync_class_hours=sync_class_hours,
            generate=generate,
            urls=urls,
            cache=cache,
            kicker=kicker,
            clock=clock,
            import_topics=import_topics,
        ),
    )


def build_emis_import(
    deps: ModuleDeps,
    *,
    schedule: ScheduleServices,
    emis: EmisSource,
    identity_commands: IdentityCommands,
    urls: LessonUrlImporter,
) -> EmisImportServices:
    """Build the EMIS import use cases on PostgreSQL."""
    return assemble_emis_import(
        uow_factory=sql_schedule_uow_factory(deps),
        emis=emis,
        identity_commands=identity_commands,
        generate=schedule.generate_lessons,
        urls=urls,
        cache=RedisRoomPageCache(deps.redis),
        kicker=deps.kicker,
        clock=deps.clock,
        import_topics=deps.settings.emis.import_topics,
    )

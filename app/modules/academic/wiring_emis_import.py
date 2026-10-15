"""Wiring of what the schedule imports from EMIS: bells, timetables, lessons."""

from dataclasses import dataclass

from app.modules.academic.application.curriculum.sync_group_curriculum import (
    SyncGroupCurriculum,
)
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.generate_lessons import GenerateLessons
from app.modules.academic.application.schedule.get_student_sync import (
    GetStudentSync,
)
from app.modules.academic.application.schedule.import_materials import (
    ImportLessonMaterials,
)
from app.modules.academic.application.schedule.ports.lesson_urls import (
    LessonMaterialImporter,
)
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.request_student_sync import (
    RequestStudentSync,
)
from app.modules.academic.application.schedule.student_sync_state import (
    SyncStateStore,
)
from app.modules.academic.application.schedule.sync_class_hours import SyncClassHours
from app.modules.academic.application.schedule.sync_group_timetable import (
    SyncGroupTimetable,
)
from app.modules.academic.application.schedule.sync_student_all import (
    SyncStudentAll,
)
from app.modules.academic.infrastructure.schedule.room_page_cache import (
    RedisRoomPageCache,
)
from app.modules.academic.infrastructure.schedule.sync_state import (
    MemorySyncState,
    RedisSyncState,
)
from app.modules.academic.wiring_schedule import (
    ScheduleServices,
    sql_schedule_uow_factory,
)
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityCommands, IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class EmisImportServices:
    """The EMIS import use cases: the bells and timetables, and the group curriculum."""

    sync_class_hours: SyncClassHours
    sync_group_timetable: SyncGroupTimetable
    sync_group_curriculum: SyncGroupCurriculum
    sync_state: SyncStateStore
    sync_student_all: SyncStudentAll
    request_student_sync: RequestStudentSync
    get_student_sync: GetStudentSync


def assemble_emis_import(
    *,
    uow_factory: UowFactory,
    emis: EmisSource,
    identity: IdentityDirectory,
    identity_commands: IdentityCommands,
    generate: GenerateLessons,
    urls: LessonMaterialImporter,
    cache: RoomPageCache,
    kicker: TaskKicker,
    clock: Clock,
    import_topics: bool = False,
    sync_state: SyncStateStore | None = None,
) -> EmisImportServices:
    """Connect the use cases to the given ports (real or fake)."""
    state = sync_state or MemorySyncState(clock.now)
    sync_class_hours = SyncClassHours(
        uow_factory=uow_factory, emis=emis, generate=generate, clock=clock
    )
    sync_group_curriculum = SyncGroupCurriculum(
        uow_factory=uow_factory, emis=emis, identity=identity, clock=clock
    )
    sync_group_timetable = SyncGroupTimetable(
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
    )
    return EmisImportServices(
        sync_class_hours=sync_class_hours,
        sync_group_timetable=sync_group_timetable,
        sync_group_curriculum=sync_group_curriculum,
        sync_state=state,
        sync_student_all=SyncStudentAll(
            uow_factory=uow_factory,
            curriculum=sync_group_curriculum,
            timetable=sync_group_timetable,
            state=state,
            kicker=kicker,
            clock=clock,
        ),
        request_student_sync=RequestStudentSync(
            state=state, kicker=kicker, clock=clock
        ),
        get_student_sync=GetStudentSync(state=state),
    )


def build_emis_import(
    deps: ModuleDeps,
    *,
    schedule: ScheduleServices,
    emis: EmisSource,
    identity: IdentityDirectory,
    identity_commands: IdentityCommands,
    links: LinksApi,
    files: FilesApi,
) -> EmisImportServices:
    """Build the EMIS import use cases on PostgreSQL."""
    urls = ImportLessonMaterials(
        emis=emis,
        files=files,
        links=links,
        max_bytes=deps.settings.limits.file_max_bytes,
        concurrency=deps.settings.emis.download_concurrency,
    )
    return assemble_emis_import(
        uow_factory=sql_schedule_uow_factory(deps),
        emis=emis,
        identity=identity,
        identity_commands=identity_commands,
        generate=schedule.generate_lessons,
        urls=urls,
        cache=RedisRoomPageCache(deps.redis),
        kicker=deps.kicker,
        clock=deps.clock,
        import_topics=deps.settings.emis.import_topics,
        sync_state=RedisSyncState(deps.redis),
    )

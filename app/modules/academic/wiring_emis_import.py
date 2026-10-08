"""Wiring of what the schedule imports from EMIS: bells and unknown groups."""

from dataclasses import dataclass

from app.modules.academic.application.schedule.bootstrap_group import BootstrapGroup
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.generate_lessons import GenerateLessons
from app.modules.academic.application.schedule.sync_class_hours import SyncClassHours
from app.modules.academic.wiring_schedule import (
    ScheduleServices,
    sql_schedule_uow_factory,
)
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.identity import IdentityCommands
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class EmisImportServices:
    """Used by the tasks `academic.sync_class_hours` and `academic.bootstrap_group`."""

    sync_class_hours: SyncClassHours
    bootstrap_group: BootstrapGroup


def assemble_emis_import(
    *,
    uow_factory: UowFactory,
    emis: EmisSource,
    identity_commands: IdentityCommands,
    generate: GenerateLessons,
    clock: Clock,
) -> EmisImportServices:
    """Connect the use cases to the given ports (real or fake)."""
    sync_class_hours = SyncClassHours(
        uow_factory=uow_factory, emis=emis, generate=generate, clock=clock
    )
    return EmisImportServices(
        sync_class_hours=sync_class_hours,
        bootstrap_group=BootstrapGroup(
            uow_factory=uow_factory,
            emis=emis,
            identity_commands=identity_commands,
            sync_class_hours=sync_class_hours,
            generate=generate,
            clock=clock,
        ),
    )


def build_emis_import(
    deps: ModuleDeps,
    *,
    schedule: ScheduleServices,
    emis: EmisSource,
    identity_commands: IdentityCommands,
) -> EmisImportServices:
    """Build the EMIS import use cases on PostgreSQL."""
    return assemble_emis_import(
        uow_factory=sql_schedule_uow_factory(deps),
        emis=emis,
        identity_commands=identity_commands,
        generate=schedule.generate_lessons,
        clock=deps.clock,
    )

"""Builds the non-lesson block services (lunch, second lunch, breaks, assemblies)."""

from dataclasses import dataclass

from app.modules.academic.application.day_blocks.use_cases import (
    CreateDayBlock,
    DeleteDayBlock,
    GetStudentDayBlocks,
    ListDayBlocks,
    UpdateDayBlock,
)
from app.modules.academic.infrastructure.day_blocks.repository import (
    SqlDayBlockStore,
)
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class DayBlockServices:
    """Admin CRUD and the student's blocks per date."""

    list_blocks: ListDayBlocks
    create_block: CreateDayBlock
    update_block: UpdateDayBlock
    delete_block: DeleteDayBlock
    student_blocks: GetStudentDayBlocks


def build_day_blocks(deps: ModuleDeps) -> DayBlockServices:
    """Wire the use cases over one SQL store."""
    store = SqlDayBlockStore(deps.sessionmaker)
    return DayBlockServices(
        list_blocks=ListDayBlocks(store),
        create_block=CreateDayBlock(store),
        update_block=UpdateDayBlock(store),
        delete_block=DeleteDayBlock(store),
        student_blocks=GetStudentDayBlocks(store, deps.clock),
    )

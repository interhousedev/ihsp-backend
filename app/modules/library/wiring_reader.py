"""Builds the reader state area of the library: shelf, progress, notes, plans."""

from dataclasses import dataclass

from app.modules.library.application.reader.annotation_writer import AnnotationWriter
from app.modules.library.application.reader.create_annotation import CreateAnnotation
from app.modules.library.application.reader.delete_annotation import DeleteAnnotation
from app.modules.library.application.reader.export_annotations import ExportAnnotations
from app.modules.library.application.reader.get_me_library import GetMeLibrary
from app.modules.library.application.reader.list_annotations import ListAnnotations
from app.modules.library.application.reader.list_shelf import ListShelf
from app.modules.library.application.reader.put_shelf_entry import PutShelfEntry
from app.modules.library.application.reader.remove_shelf_entry import RemoveShelfEntry
from app.modules.library.application.reader.save_progress import SaveProgress
from app.modules.library.application.reader.sync_annotations import SyncAnnotations
from app.modules.library.application.reader.update_annotation import UpdateAnnotation
from app.modules.library.ports.lesson_directory import LessonDirectory
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class ReaderServices:
    """Use cases of the reader state area."""

    put_shelf_entry: PutShelfEntry
    remove_shelf_entry: RemoveShelfEntry
    list_shelf: ListShelf
    get_me_library: GetMeLibrary
    save_progress: SaveProgress
    create_annotation: CreateAnnotation
    sync_annotations: SyncAnnotations
    list_annotations: ListAnnotations
    update_annotation: UpdateAnnotation
    delete_annotation: DeleteAnnotation
    export_annotations: ExportAnnotations


def build_reader(
    core: LibraryCore, lessons: LessonDirectory | None = None
) -> ReaderServices:
    """Wire the use cases of the reader area."""
    writer = AnnotationWriter(clock=core.clock)
    return ReaderServices(
        put_shelf_entry=PutShelfEntry(
            uow_factory=core.uow_factory, clock=core.clock, cards=core.cards
        ),
        remove_shelf_entry=RemoveShelfEntry(uow_factory=core.uow_factory),
        list_shelf=ListShelf(uow_factory=core.uow_factory, cards=core.cards),
        get_me_library=GetMeLibrary(
            uow_factory=core.uow_factory, cards=core.cards, settings=core.settings
        ),
        save_progress=SaveProgress(uow_factory=core.uow_factory, clock=core.clock),
        create_annotation=CreateAnnotation(uow_factory=core.uow_factory, writer=writer),
        sync_annotations=SyncAnnotations(
            uow_factory=core.uow_factory, writer=writer, clock=core.clock
        ),
        list_annotations=ListAnnotations(uow_factory=core.uow_factory),
        update_annotation=UpdateAnnotation(
            uow_factory=core.uow_factory, clock=core.clock
        ),
        delete_annotation=DeleteAnnotation(
            uow_factory=core.uow_factory, clock=core.clock
        ),
        export_annotations=ExportAnnotations(uow_factory=core.uow_factory),
    )

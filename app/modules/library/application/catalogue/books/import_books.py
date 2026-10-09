"""Bulk import of books from a CSV (POST /manage/library/import)."""

from dataclasses import dataclass
from pathlib import PurePath
from uuid import UUID

from app.modules.library.application.catalogue.books.attach_book_file import (
    BOOK_FORMATS,
    PROCESS_TASK,
)
from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.catalogue_books import new_book
from app.modules.library.domain.catalogue_errors import ImportInvalidError
from app.modules.library.domain.catalogue_import import (
    ImportRow,
    ProblemCode,
    RowProblem,
    parse_books_csv,
)
from app.modules.library.domain.entities import ItemFile
from app.modules.library.domain.enums import EventKind, FileFormat, TextStatus
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.files import FileRef, FilesApi, FileScope
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

OWNED_FILES_SCAN = 1000
_EXTENSIONS = {
    ".pdf": FileFormat.PDF,
    ".epub": FileFormat.EPUB,
    ".md": FileFormat.MD,
    ".txt": FileFormat.TXT,
}


@dataclass(frozen=True, slots=True)
class CreatedRow:
    """A draft made from a row; `file_id` when a file was attached."""

    item_id: UUID
    file_id: UUID | None


@dataclass(frozen=True, slots=True)
class ImportErrorView:
    """One entry of `ImportResult.errors`."""

    row: int
    message: str


@dataclass(frozen=True, slots=True)
class ImportResultView:
    """`ImportResult` of the TypeScript contract."""

    created: int
    errors: list[ImportErrorView]


class ImportBooks:
    """Good rows become draft books (files attached by name); bad rows are listed."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        support: BookSupport,
        files: FilesApi,
        i18n: I18nCore,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.support = support
        self.files = files
        self.i18n = i18n
        self.kicker = kicker

    async def execute(
        self, actor: Actor, csv_file_id: UUID, *, accept_language: str | None = None
    ) -> ImportResultView:
        """Read the CSV, create the drafts of the good rows, report the others."""
        require_librarian(actor)
        locale = await resolve_locale(self.support.identity, actor, accept_language)
        text = await self._read_csv(actor, csv_file_id)
        subjects = await self._subject_names(locale)
        parsed = parse_books_csv(text, subjects=subjects)
        uploads = await self._uploads(actor)
        problems = list(parsed.problems)
        scans: list[tuple[UUID, UUID]] = []
        created = 0
        async with self.uow_factory() as uow:
            for row in parsed.rows:
                outcome = await self._create_row(uow, actor, row, uploads)
                if isinstance(outcome, RowProblem):
                    problems.append(outcome)
                    continue
                created += 1
                if outcome.file_id is not None:
                    scans.append((outcome.item_id, outcome.file_id))
            uow.after_commit(lambda: self._queue_scans(scans))
            await uow.commit()
        problems.sort(key=lambda p: p.row)
        return ImportResultView(
            created=created,
            errors=[self._message(problem, locale) for problem in problems],
        )

    async def _read_csv(self, actor: Actor, csv_file_id: UUID) -> str:
        ref = await self.files.get(csv_file_id)
        if ref is None or ref.owner_id != actor.user_id:
            raise ImportInvalidError(support_details="csv file is not usable")
        data = await self.files.read_bytes(csv_file_id)
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ImportInvalidError(support_details="csv is not UTF-8") from error

    async def _subject_names(self, locale: str) -> dict[str, UUID]:
        known: dict[str, UUID] = {}
        for subject in await self.support.academic.list_subjects(locale):
            known[subject.name.strip().lower()] = subject.id
            known[str(subject.id)] = subject.id
        return known

    async def _uploads(self, actor: Actor) -> dict[str, FileRef]:
        owned = await self.files.list_owned(actor.user_id, limit=OWNED_FILES_SCAN)
        return {
            ref.name: ref
            for ref in reversed(owned)
            if ref.scope is FileScope.LIBRARY and ref.status == "ready"
        }

    async def _create_row(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        row: ImportRow,
        uploads: dict[str, FileRef],
    ) -> RowProblem | CreatedRow:
        upload = uploads.get(row.file_name) if row.file_name else None
        file_format = _format_of(row.file_name)
        if row.file_name and (upload is None or file_format is None):
            return RowProblem(
                row.row, ProblemCode.FILE_NOT_FOUND, {"value": row.file_name}
            )
        try:
            await self.support.validate_refs(uow, actor, row.data)
        except BaseError as error:
            return RowProblem(
                row.row,
                ProblemCode.INVALID,
                {"field": str(error.params.get("field", ""))},
            )
        now = self.support.clock.now()
        item = new_book(row.data, item_id=new_id(), owner_id=actor.user_id, now=now)
        if upload is not None and file_format is not None:
            item.files.append(_item_file(item.id, upload, file_format))
        await uow.items.add(item)
        await uow.items.set_subject_links(item.id, row.data.subjects)
        await uow.items.set_topic_links(item.id, row.data.topics)
        await uow.events.append(
            item.id,
            EventKind.CREATED,
            at=now,
            actor_id=actor.user_id,
            data={"import": True},
        )
        return CreatedRow(item.id, upload.id if upload is not None else None)

    def _message(self, problem: RowProblem, locale: str) -> ImportErrorView:
        key = f"library-import-{problem.code.value}"
        return ImportErrorView(problem.row, self.i18n.t(locale, key, **problem.params))

    async def _queue_scans(self, scans: list[tuple[UUID, UUID]]) -> None:
        for item_id, file_id in scans:
            await self.kicker.kick(
                PROCESS_TASK, item_id=str(item_id), file_id=str(file_id)
            )


def _format_of(file_name: str | None) -> FileFormat | None:
    if not file_name:
        return None
    found = _EXTENSIONS.get(PurePath(file_name).suffix.lower())
    return found if found in BOOK_FORMATS else None


def _item_file(item_id: UUID, ref: FileRef, file_format: FileFormat) -> ItemFile:
    return ItemFile(
        item_id=item_id,
        file_id=ref.id,
        format=file_format,
        byte_size=ref.byte_size,
        is_primary=True,
        text_status=TextStatus.PENDING,
    )

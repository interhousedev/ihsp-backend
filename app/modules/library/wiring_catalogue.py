"""Builds the catalogue area of the library."""

from dataclasses import dataclass

from app.modules.library.application.catalogue.books.attach_book_file import (
    AttachBookFile,
)
from app.modules.library.application.catalogue.books.change_book_status import (
    PublishBook,
    TakedownBook,
    UnpublishBook,
)
from app.modules.library.application.catalogue.books.create_book import CreateBook
from app.modules.library.application.catalogue.books.get_book_draft import GetBookDraft
from app.modules.library.application.catalogue.books.import_books import ImportBooks
from app.modules.library.application.catalogue.books.list_books import ListBooks
from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.books.update_book import UpdateBook
from app.modules.library.application.catalogue.get_file_url import GetFileUrl
from app.modules.library.application.catalogue.get_item import GetItem
from app.modules.library.application.catalogue.get_item_text import GetItemText
from app.modules.library.application.catalogue.list_items import ListItems
from app.modules.library.application.catalogue.list_subjects import ListSubjects
from app.modules.library.application.catalogue.process_item_file import ProcessItemFile
from app.modules.library.application.catalogue.public_pages import (
    GetPublicItemPage,
    ListSitemap,
)
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class CatalogueServices:
    """Use cases of the catalogue area."""

    list_items: ListItems
    get_item: GetItem
    get_file_url: GetFileUrl
    get_item_text: GetItemText
    list_subjects: ListSubjects
    create_book: CreateBook
    update_book: UpdateBook
    get_book_draft: GetBookDraft
    list_books: ListBooks
    attach_book_file: AttachBookFile
    publish_book: PublishBook
    unpublish_book: UnpublishBook
    takedown_book: TakedownBook
    import_books: ImportBooks
    process_item_file: ProcessItemFile
    get_public_item_page: GetPublicItemPage
    list_sitemap: ListSitemap


def build_catalogue(core: LibraryCore) -> CatalogueServices:
    """Wire the use cases of the catalogue area."""
    uow_factory = core.uow_factory
    support = BookSupport(
        academic=core.academic,
        files=core.files,
        detail=core.detail,
        identity=core.identity,
        clock=core.clock,
        settings=core.settings,
    )
    return CatalogueServices(
        list_items=ListItems(
            uow_factory=uow_factory,
            cards=core.cards,
            identity=core.identity,
            settings=core.settings,
            stats=core.stats,
        ),
        get_item=GetItem(
            uow_factory=uow_factory,
            detail=core.detail,
            identity=core.identity,
            settings=core.settings,
        ),
        get_file_url=GetFileUrl(
            uow_factory=uow_factory,
            files=core.files,
            stats=core.stats,
            clock=core.clock,
            settings=core.settings,
        ),
        get_item_text=GetItemText(
            uow_factory=uow_factory, files=core.files, settings=core.settings
        ),
        list_subjects=ListSubjects(
            uow_factory=uow_factory,
            academic=core.academic,
            identity=core.identity,
            settings=core.settings,
        ),
        create_book=CreateBook(uow_factory=uow_factory, support=support),
        update_book=UpdateBook(uow_factory=uow_factory, support=support),
        get_book_draft=GetBookDraft(uow_factory=uow_factory, support=support),
        list_books=ListBooks(
            uow_factory=uow_factory, cards=core.cards, identity=core.identity
        ),
        attach_book_file=AttachBookFile(
            uow_factory=uow_factory,
            support=support,
            files=core.files,
            kicker=core.kicker,
        ),
        publish_book=PublishBook(uow_factory=uow_factory, support=support),
        unpublish_book=UnpublishBook(uow_factory=uow_factory, support=support),
        takedown_book=TakedownBook(uow_factory=uow_factory, support=support),
        import_books=ImportBooks(
            uow_factory=uow_factory,
            support=support,
            files=core.files,
            i18n=core.i18n,
            kicker=core.kicker,
        ),
        process_item_file=ProcessItemFile(
            uow_factory=uow_factory, files=core.files, clock=core.clock
        ),
        get_public_item_page=GetPublicItemPage(
            uow_factory=uow_factory,
            cards=core.cards,
            identity=core.identity,
            i18n=core.i18n,
            settings=core.settings,
        ),
        list_sitemap=ListSitemap(uow_factory=uow_factory, settings=core.settings),
    )

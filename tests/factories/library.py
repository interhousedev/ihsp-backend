"""Factories of the library tests: items of each kind in any state."""

import datetime as dt
from uuid import UUID

from app.modules.library.domain.entities import (
    BookDetails,
    ExternalDetails,
    Item,
    ItemFile,
    MaterialDetails,
)
from app.modules.library.domain.enums import (
    Approval,
    ExternalAccess,
    ExternalSource,
    FileFormat,
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    MaterialLicence,
    Rights,
    TextStatus,
    UploaderRole,
    Visibility,
)
from app.modules.library.domain.slugs import make_slug
from app.shared.ids import new_id

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def make_book(
    *,
    title: str = "Physics 10",
    status: ItemStatus = ItemStatus.PUBLISHED,
    visibility: Visibility = Visibility.LYCEUM,
    rights: Rights = Rights.OFFICIAL,
    owner_id: UUID | None = None,
    file_id: UUID | None = None,
    text_status: TextStatus = TextStatus.READY,
    download_allowed: bool = False,
    now: dt.datetime = NOW,
    **fields: object,
) -> Item:
    """A hosted book with one primary PDF file."""
    item_id = new_id()
    item = Item(
        id=item_id,
        slug=make_slug(title, item_id),
        kind=ItemKind.BOOK,
        type=ItemType.TEXTBOOK,
        title=title,
        language=ItemLanguage.UZ_LATN,
        status=status,
        visibility=visibility,
        created_at=now,
        updated_at=now,
        authors=["A. Author"],
        author_label="A. Author",
        owner_id=owner_id or new_id(),
        download_allowed=download_allowed,
        has_text=text_status is TextStatus.READY,
        page_count=120,
        published_at=now if status is ItemStatus.PUBLISHED else None,
        search_text=title.lower(),
        book=BookDetails(
            rights=rights,
            rights_basis={"rule": "test"},
            rights_checked_at=now,
        ),
        files=[
            ItemFile(
                item_id=item_id,
                file_id=file_id or new_id(),
                format=FileFormat.PDF,
                byte_size=1000,
                is_primary=True,
                pages=120,
                text_status=text_status,
            )
        ],
    )
    for key, value in fields.items():
        setattr(item, key, value)
    return item


def make_material(
    *,
    title: str = "Kinematics notes",
    status: ItemStatus = ItemStatus.PUBLISHED,
    visibility: Visibility = Visibility.LYCEUM,
    uploader_id: UUID | None = None,
    uploader_role: UploaderRole = UploaderRole.STUDENT,
    approval: Approval | None = Approval.LIBRARIAN,
    now: dt.datetime = NOW,
    **fields: object,
) -> Item:
    """A material with one primary PDF file, uploaded by `uploader_id`."""
    item_id = new_id()
    uploader = uploader_id or new_id()
    item = Item(
        id=item_id,
        slug=make_slug(title, item_id),
        kind=ItemKind.MATERIAL,
        type=ItemType.NOTES,
        title=title,
        language=ItemLanguage.UZ_LATN,
        status=status,
        visibility=visibility,
        created_at=now,
        updated_at=now,
        owner_id=uploader,
        created_by=uploader,
        has_text=True,
        page_count=4,
        search_text=title.lower(),
        published_at=now if status is ItemStatus.PUBLISHED else None,
        material=MaterialDetails(
            uploader_id=uploader,
            uploader_role=uploader_role,
            uploader_name="Aziza K.",
            uploader_cohort="2025",
            licence=MaterialLicence.ALL_RIGHTS_RESERVED,
            attested_at=now,
            approval=approval,
            submitted_at=now,
        ),
        files=[
            ItemFile(
                item_id=item_id,
                file_id=new_id(),
                format=FileFormat.PDF,
                byte_size=500,
                is_primary=True,
                pages=4,
                text_status=TextStatus.READY,
            )
        ],
    )
    for key, value in fields.items():
        setattr(item, key, value)
    return item


def make_external(
    *,
    title: str = "Elektronika va sxemalar 1",
    external_id: str = "355186",
    status: ItemStatus = ItemStatus.PUBLISHED,
    now: dt.datetime = NOW,
    **fields: object,
) -> Item:
    """A stored UniLibrary record (link-only, no files)."""
    item_id = new_id()
    item = Item(
        id=item_id,
        slug=make_slug(title, item_id),
        kind=ItemKind.EXTERNAL,
        type=ItemType.TEXTBOOK,
        title=title,
        language=ItemLanguage.UZ_LATN,
        status=status,
        visibility=Visibility.LYCEUM,
        created_at=now,
        updated_at=now,
        search_text=title.lower(),
        external=ExternalDetails(
            source=ExternalSource.UNILIBRARY,
            external_id=external_id,
            category=1,
            access=ExternalAccess.PARTIAL,
            view_url=f"https://unilibrary.uz/literature/{external_id}",
            snapshot_hash="0" * 64,
            fetched_at=now,
            type_name={"uz": "Darslik"},
            field_name={"uz": "Fizika"},
        ),
    )
    for key, value in fields.items():
        setattr(item, key, value)
    return item

"""ORM models of library.items and its per-kind detail tables, files and pages."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

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
from app.modules.library.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CHAR,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

SEARCH_VECTOR = "to_tsvector('simple', coalesce(search_text, ''))"
PAGE_VECTOR = "to_tsvector('simple', coalesce(text_norm, ''))"


class Item(IdMixin, TimestampMixin, Base):
    """A catalogue item of any kind (UniLibrary record, book or material).

    `search_text` holds the Latin-normalised title, subtitle, authors and description
    (not the body); the body is searched in `item_pages`.
    """

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_items_slug"),
        CheckConstraint(
            "kind <> 'external' OR cover_file_id IS NULL", name="external_no_file"
        ),
        Index("ix_items_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_items_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_items_kind_status_visibility", "kind", "status", "visibility"),
        Index("ix_items_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_items_status_updated_at", "status", "updated_at"),
        Index("ix_items_content_hash", "content_hash"),
        {"schema": "library"},
    )

    slug: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(str_enum(ItemKind, "kind"))
    type: Mapped[str] = mapped_column(str_enum(ItemType, "type"))
    title: Mapped[str] = mapped_column(String(255))
    title_alt: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    subtitle: Mapped[str | None] = mapped_column(String(255))
    authors: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default=text("'{}'::varchar[]")
    )
    author_label: Mapped[str] = mapped_column(String(255), server_default="")
    language: Mapped[str] = mapped_column(str_enum(ItemLanguage, "language"))
    year_published: Mapped[int | None] = mapped_column(SmallInteger)
    publisher: Mapped[str | None] = mapped_column(String(255))
    isbn: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    cover_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    cover_url: Mapped[str | None] = mapped_column(Text)
    years_of_study: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), server_default=text("'{}'::smallint[]")
    )
    status: Mapped[str] = mapped_column(str_enum(ItemStatus, "status"))
    status_reason: Mapped[str | None] = mapped_column(String(40))
    status_note: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(str_enum(Visibility, "visibility"))
    download_allowed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    has_text: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    page_count: Mapped[int | None] = mapped_column(Integer)
    search_text: Mapped[str] = mapped_column(Text, server_default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True), deferred=True
    )
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))
    owner_id: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid)
    open_reports: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)


class ExternalDetails(TimestampMixin, Base):
    """Snapshot of an external (UniLibrary) record; one row per `external` item."""

    __tablename__ = "external_details"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_details_source"),
        Index("ix_external_details_gone_at", "gone_at"),
        Index("ix_external_details_fetched_at", "fetched_at"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(str_enum(ExternalSource, "source"))
    external_id: Mapped[str] = mapped_column(String(40))
    category: Mapped[int] = mapped_column(SmallInteger)
    access: Mapped[str] = mapped_column(str_enum(ExternalAccess, "access"))
    type_name: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    field_name: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    language_name: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    view_url: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(CHAR(64))
    feed_id: Mapped[UUID | None] = mapped_column(Uuid)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookDetails(TimestampMixin, Base):
    """Rights data of a hosted book; one row per `book` item."""

    __tablename__ = "book_details"
    __table_args__ = ({"schema": "library"},)

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    rights: Mapped[str] = mapped_column(str_enum(Rights, "rights"))
    licence: Mapped[str | None] = mapped_column(String(40))
    rights_basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    rights_proof_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    rights_checked_by: Mapped[UUID | None] = mapped_column(Uuid)
    rights_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    translators: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default=text("'{}'::varchar[]")
    )


class MaterialDetails(TimestampMixin, Base):
    """Uploader snapshot, licence, approval and scan findings of a material."""

    __tablename__ = "material_details"
    __table_args__ = (
        Index(
            "ix_material_details_uploader_id_submitted_at",
            "uploader_id",
            "submitted_at",
        ),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    uploader_id: Mapped[UUID] = mapped_column(Uuid)
    uploader_role: Mapped[str] = mapped_column(str_enum(UploaderRole, "uploader_role"))
    uploader_name: Mapped[str] = mapped_column(String(80))
    uploader_cohort: Mapped[str] = mapped_column(String(20), server_default="")
    licence: Mapped[str] = mapped_column(str_enum(MaterialLicence, "licence"))
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval: Mapped[str | None] = mapped_column(str_enum(Approval, "approval"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_message: Mapped[str | None] = mapped_column(Text)
    scan: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class ItemFile(TimestampMixin, Base):
    """A file of a book or material (the bytes live in the files module)."""

    __tablename__ = "item_files"
    __table_args__ = (
        Index(
            "ix_item_files_primary",
            "item_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        Index("ix_item_files_sha256", "sha256"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    format: Mapped[str] = mapped_column(str_enum(FileFormat, "format"))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    pages: Mapped[int | None] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    readable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    text_status: Mapped[str] = mapped_column(
        str_enum(TextStatus, "text_status"), server_default="none"
    )
    toc: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    sha256: Mapped[str | None] = mapped_column(CHAR(64))


class ItemPage(TimestampMixin, Base):
    """One page of extracted text, Latin-normalised, for full-text hits with a page.

    An addition to doc § 6.1: the doc searches "the full text of books and materials
    (snippet and page)" without naming where the pages are indexed.
    """

    __tablename__ = "item_pages"
    __table_args__ = (
        Index("ix_item_pages_search_vector", "search_vector", postgresql_using="gin"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    text_norm: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(PAGE_VECTOR, persisted=True), deferred=True
    )


class ItemStat(TimestampMixin, Base):
    """Daily counters of an item, rolled up from Redis."""

    __tablename__ = "item_stats"
    __table_args__ = ({"schema": "library"},)

    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    opens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    readers: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    offline_saves: Mapped[int] = mapped_column(Integer, server_default=text("0"))

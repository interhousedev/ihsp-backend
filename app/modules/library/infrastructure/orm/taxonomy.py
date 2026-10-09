"""ORM models of subjects/topics tagging, collections and reading lists."""

from datetime import date
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
    SubjectRole,
)
from app.modules.library.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Topic(IdMixin, TimestampMixin, Base):
    """A topic of a subject; topics form a tree per subject."""

    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "parent_id",
            "slug",
            name="uq_topics_subject_id",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_topics_subject_id_position", "subject_id", "position"),
        {"schema": "library"},
    )

    subject_id: Mapped[UUID] = mapped_column(Uuid)
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("library.topics.id", ondelete="CASCADE")
    )
    name: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    slug: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    year_of_study: Mapped[int | None] = mapped_column(SmallInteger)


class ItemSubject(TimestampMixin, Base):
    """An item belongs to a subject (optionally for one year of study)."""

    __tablename__ = "item_subjects"
    __table_args__ = (
        Index("ix_item_subjects_subject_id", "subject_id"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # 0 means "any year": a primary key column cannot be NULL.
    year_of_study: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, server_default=text("0")
    )
    role: Mapped[str] = mapped_column(
        str_enum(SubjectRole, "role"), server_default="supplementary"
    )


class ItemTopic(TimestampMixin, Base):
    """An item (or a page range of it) feeds a topic."""

    __tablename__ = "item_topics"
    __table_args__ = (
        Index("ix_item_topics_topic_id", "topic_id"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.topics.id", ondelete="CASCADE"), primary_key=True
    )
    # 0 means "the whole item": a primary key column cannot be NULL.
    page_from: Mapped[int] = mapped_column(
        Integer, primary_key=True, server_default=text("0")
    )
    page_to: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Collection(IdMixin, TimestampMixin, Base):
    """A librarian-curated shelf not tied to a subject."""

    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_collections_slug"),
        {"schema": "library"},
    )

    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    description: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    cover_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    published: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class CollectionItem(TimestampMixin, Base):
    """An item on a collection."""

    __tablename__ = "collection_items"
    __table_args__ = (
        Index("ix_collection_items_item_id", "item_id"),
        {"schema": "library"},
    )

    collection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.collections.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class ReadingList(IdMixin, TimestampMixin, Base):
    """A teacher's or librarian's reading list for a subject, groups or the school."""

    __tablename__ = "reading_lists"
    __table_args__ = (
        Index("ix_reading_lists_group_ids", "group_ids", postgresql_using="gin"),
        Index("ix_reading_lists_subject_id_status", "subject_id", "status"),
        Index("ix_reading_lists_owner_id", "owner_id"),
        {"schema": "library"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(str_enum(ListScope, "scope"))
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    group_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    year_of_study: Mapped[int | None] = mapped_column(SmallInteger)
    academic_year: Mapped[str | None] = mapped_column(String(9))
    term_half: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(
        str_enum(ListStatus, "status"), server_default="draft"
    )


class ReadingListItem(TimestampMixin, Base):
    """An entry of a reading list: a library item or a plain link."""

    __tablename__ = "reading_list_items"
    __table_args__ = (
        CheckConstraint("item_id IS NOT NULL OR url IS NOT NULL", name="item_or_url"),
        Index("ix_reading_list_items_item_id", "item_id"),
        {"schema": "library"},
    )

    list_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("library.reading_lists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[UUID | None] = mapped_column(Uuid)
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255))
    importance: Mapped[str] = mapped_column(
        str_enum(Importance, "importance"), server_default="recommended"
    )
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    week_label: Mapped[str | None] = mapped_column(String(40))
    due_on: Mapped[date | None] = mapped_column()
    topic_id: Mapped[UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(500))

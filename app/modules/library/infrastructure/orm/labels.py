"""ORM models of authors and tags (names as typed, one loose key per name)."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class Author(IdMixin, TimestampMixin, Base):
    """A person who wrote books; `name_key` makes Latin and Cyrillic spellings meet."""

    __tablename__ = "authors"
    __table_args__ = (
        UniqueConstraint("name_key", name="uq_authors_name_key"),
        Index(
            "ix_authors_name_key_trgm",
            "name_key",
            postgresql_using="gin",
            postgresql_ops={"name_key": "gin_trgm_ops"},
        ),
        {"schema": "library"},
    )

    name: Mapped[str] = mapped_column(String(255))
    name_key: Mapped[str] = mapped_column(String(255))


class ItemAuthor(TimestampMixin, Base):
    """An author of an item, in the order of the title page."""

    __tablename__ = "item_authors"
    __table_args__ = (
        Index("ix_item_authors_author_id", "author_id"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.authors.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Tag(IdMixin, TimestampMixin, Base):
    """A free label on items; created when first used, reused afterwards."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("name_key", name="uq_tags_name_key"),
        Index(
            "ix_tags_name_key_trgm",
            "name_key",
            postgresql_using="gin",
            postgresql_ops={"name_key": "gin_trgm_ops"},
        ),
        {"schema": "library"},
    )

    name: Mapped[str] = mapped_column(String(40))
    name_key: Mapped[str] = mapped_column(String(40))


class ItemTag(TimestampMixin, Base):
    """A tag on an item."""

    __tablename__ = "item_tags"
    __table_args__ = (
        Index("ix_item_tags_tag_id", "tag_id"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.tags.id", ondelete="CASCADE"), primary_key=True
    )

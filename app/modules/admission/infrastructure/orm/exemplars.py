"""ORM of the exemplar essay library."""

from uuid import UUID

from app.modules.admission.domain.exemplars import EXEMPLAR_KINDS, EXEMPLAR_STATUSES
from app.modules.admission.infrastructure.orm._common import (
    SCHEMA,
    CreatedMixin,
    LockMixin,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["ExemplarRow"]


class ExemplarRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """One exemplar essay with the public source it was taken from."""

    __tablename__ = "exemplar_essays"
    __table_args__ = (
        check_in("kind", EXEMPLAR_KINDS),
        check_in("status", EXEMPLAR_STATUSES),
        CheckConstraint("source_url LIKE 'https://%'", name="source_url_https"),
        CheckConstraint("cardinality(tags) <= 12", name="tags_count"),
        CheckConstraint("word_count >= 0", name="word_count_nonnegative"),
        max_len("body", 20000),
        max_len("prompt", 4000),
        max_len("title", 200),
        Index("ix_exemplar_essays_status_kind", "status", "kind"),
        Index("ix_exemplar_essays_institution_id", "institution_id"),
        Index("ix_exemplar_essays_source", "source_url", "title"),
        {"schema": SCHEMA},
    )

    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.institutions.id", ondelete="SET NULL")
    )
    school_name: Mapped[str] = mapped_column(String(200), server_default=text("''"))
    year: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text, server_default=text("''"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(200), server_default=text("''"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    notes: Mapped[str] = mapped_column(Text, server_default=text("''"))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    language: Mapped[str] = mapped_column(String(5), server_default=text("'en'"))
    created_by: Mapped[UUID | None] = mapped_column()
    updated_by: Mapped[UUID | None] = mapped_column()

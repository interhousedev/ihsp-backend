"""ORM model of notebooks.artifact_assets."""

from enum import StrEnum
from uuid import UUID

from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class AssetKind(StrEnum):
    """Kinds of files that belong to an output (reserved: nothing writes them)."""

    AUDIO_TURN = "audio_turn"


class ArtifactAsset(IdMixin, TimestampMixin, Base):
    """A stored file of an output, e.g. one spoken turn of an audio overview."""

    __tablename__ = "artifact_assets"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id", "kind", "idx", name="uq_artifact_assets_artifact_id_kind_idx"
        ),
        {"schema": "notebooks"},
    )

    artifact_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.artifacts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(str_enum(AssetKind, "kind"))
    idx: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[UUID] = mapped_column(Uuid)
    duration_ms: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)

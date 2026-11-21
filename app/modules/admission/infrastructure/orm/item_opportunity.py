"""The opportunity an activity is linked to: a pending submission or a catalog entry."""

from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
)
from app.shared.db.base import Base

from sqlalchemy import ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class ItemOpportunityLinkRow(CreatedMixin, UpdatedMixin, Base):
    """One link per item; approval of the submission fills `opportunity_id`."""

    __tablename__ = "item_opportunity_links"
    __table_args__ = (
        Index("ix_item_opportunity_links_submission_id", "submission_id"),
        Index("ix_item_opportunity_links_opportunity_id", "opportunity_id"),
        S,
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("admission.items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    submission_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("admission.opportunity_submissions.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("admission.opportunities.id", ondelete="SET NULL")
    )

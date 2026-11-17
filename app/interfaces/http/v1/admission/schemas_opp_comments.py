"""Schemas of comments under opportunities and their reports."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.admission.application.opportunity_comments import (
    CommentView,
    ReportView,
)

from pydantic import BaseModel, Field


class OppCommentIn(BaseModel):
    """Post a comment."""

    body: str = Field(min_length=1, max_length=2000)


class OppReportIn(BaseModel):
    """Report a comment."""

    reason: str = Field(min_length=1, max_length=500)


class OppCommentOut(BaseModel):
    """A comment; hidden ones reach staff only."""

    id: UUID
    opportunity_id: UUID
    author_id: UUID
    author_name: str
    body: str
    status: Literal["published", "hidden", "deleted"]
    created_at: dt.datetime

    @classmethod
    def of(cls, v: CommentView) -> "OppCommentOut":
        """Map a comment view."""
        c = v.comment
        return cls(
            id=c.id,
            opportunity_id=c.opportunity_id,
            author_id=c.author_id,
            author_name=v.author_name,
            body=c.body,
            status=c.status,
            created_at=c.created_at,
        )


class OppCommentListOut(BaseModel):
    """Comments of one entry."""

    items: list[OppCommentOut]


class OppReportOut(BaseModel):
    """A report in the staff queue."""

    id: UUID
    comment: OppCommentOut
    reporter_id: UUID
    reporter_name: str
    reason: str
    created_at: dt.datetime

    @classmethod
    def of(cls, v: ReportView) -> "OppReportOut":
        """Map a report view."""
        return cls(
            id=v.report.id,
            comment=OppCommentOut.of(CommentView(v.comment, v.author_name)),
            reporter_id=v.report.reporter_id,
            reporter_name=v.reporter_name,
            reason=v.report.reason,
            created_at=v.report.created_at,
        )


class OppReportListOut(BaseModel):
    """The staff queue of open reports."""

    items: list[OppReportOut]

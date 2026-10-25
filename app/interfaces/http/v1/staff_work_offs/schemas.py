"""Request and response models of the staff work-off endpoints."""

import datetime as dt
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class WorkOffTemplateBody(BaseModel):
    """Body of ``POST`` and ``PUT /v1/staff/work-off-templates``."""

    text: str
    is_default: bool = False


class WorkOffTemplateResponse(BaseModel):
    """A reusable work-off text of a teacher."""

    id: UUID
    text: str
    is_default: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class WorkOffPatchBody(BaseModel):
    """Body of ``PATCH /v1/staff/work-offs/{id}``; only sent fields change."""

    text: str | None = None
    due_date: dt.date | None = None
    status: Literal["assigned", "done"] | None = None

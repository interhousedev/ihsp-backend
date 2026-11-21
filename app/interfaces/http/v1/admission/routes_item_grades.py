"""Move an item between draft and ready, and AI-grade one item."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_items import (
    ItemGradeOut,
    ItemListOut,
    ItemOut,
    LocaleHeader,
    _locale,
)

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class ItemMoveIn(BaseModel):
    """Target column and position inside it (0 = first)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "ready"]
    index: int = Field(ge=0, le=100)


async def move_item(
    item_id: UUID, body: ItemMoveIn, container: ContainerDep, ctx: AdmissionCtx
) -> ItemListOut:
    """Drop an activity or honor into a column at a position."""
    await container.admission.items.move(ctx, item_id, body.status, body.index)
    views = await container.admission.items.list_items(ctx, ctx.user_id)
    return ItemListOut(items=[ItemOut.of(v) for v in views])


async def grade_item(
    item_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: LocaleHeader = None,
) -> ItemGradeOut:
    """Grade the title and description A-E (cached per content)."""
    locale = _locale(accept_language)
    grade = await container.admission.item_grades.grade(ctx, item_id, locale)
    return ItemGradeOut.of(grade, locale)


router.add_api_route(
    "/me/items/{item_id}/move",
    move_item,
    methods=["POST"],
    response_model=ItemListOut,
    operation_id="admission_move_item",
    status_code=status.HTTP_200_OK,
)
router.add_api_route(
    "/me/items/{item_id}/grade",
    grade_item,
    methods=["POST"],
    response_model=ItemGradeOut,
    operation_id="admission_grade_item",
    status_code=status.HTTP_200_OK,
)

"""Routes of textbook plans and of the books a lesson follows."""

from app.interfaces.http.v1.library.reader.handlers import (
    get_book_plan,
    get_lesson_item_refs,
    put_book_plan,
    set_lesson_item_refs,
    suggest_next_section,
)

from fastapi import APIRouter

router = APIRouter(tags=["library"])

router.add_api_route(
    "/v1/library/book-plans", get_book_plan.get_book_plan, methods=["GET"]
)
router.add_api_route(
    "/v1/library/book-plans", put_book_plan.put_book_plan, methods=["PUT"]
)
router.add_api_route(
    "/v1/staff/library/book-plans/next",
    suggest_next_section.suggest_next_section,
    methods=["GET"],
)
router.add_api_route(
    "/v1/me/lessons/{lesson_id}/item-refs",
    get_lesson_item_refs.get_lesson_item_refs,
    methods=["GET"],
)
router.add_api_route(
    "/v1/staff/lessons/{lesson_id}/item-refs",
    set_lesson_item_refs.set_lesson_item_refs,
    methods=["PUT"],
)

"""Routes of the librarian's book management."""

from app.interfaces.http.v1.library.catalogue.handlers import (
    attach_book_file,
    book_actions,
    create_book,
    get_book,
    import_books,
    list_books,
    update_book,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/manage/library", tags=["library-manage"])

router.add_api_route("/books", list_books.list_books, methods=["GET"])
router.add_api_route(
    "/books",
    create_book.create_book,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route("/books/{book_id}", get_book.get_book, methods=["GET"])
router.add_api_route("/books/{book_id}", update_book.update_book, methods=["PATCH"])
router.add_api_route(
    "/books/{book_id}/files",
    attach_book_file.attach_book_file,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/books/{book_id}/publish", book_actions.publish_book, methods=["POST"]
)
router.add_api_route(
    "/books/{book_id}/unpublish", book_actions.unpublish_book, methods=["POST"]
)
router.add_api_route(
    "/books/{book_id}/takedown", book_actions.takedown_book, methods=["POST"]
)
router.add_api_route("/import", import_books.import_books, methods=["POST"])

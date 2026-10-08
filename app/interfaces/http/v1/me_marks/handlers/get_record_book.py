"""GET /v1/me/record-book."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_record_book(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Return every semester with its GPA and semester marks."""
    book: dict[str, Any] = await container.academic.marks.get_record_book.execute(actor)
    return book

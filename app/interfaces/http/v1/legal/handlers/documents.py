"""Public routes: GET /v1/legal/documents[/{kind}]."""

from app.interfaces.http.v1.legal.deps import ContainerDep, Locale
from app.interfaces.http.v1.legal.schemas import (
    LegalDocumentListOut,
    LegalDocumentOut,
    LegalKindValue,
)


async def list_documents(
    container: ContainerDep, locale: Locale
) -> LegalDocumentListOut:
    """The current published version of every kind that has one."""
    documents = await container.legal.list_current.execute()
    return LegalDocumentListOut(
        items=[LegalDocumentOut.of(d, locale) for d in documents]
    )


async def get_document(
    kind: LegalKindValue, container: ContainerDep, locale: Locale
) -> LegalDocumentOut:
    """The current published version of one kind (404 when none)."""
    return LegalDocumentOut.of(await container.legal.get_current.execute(kind), locale)

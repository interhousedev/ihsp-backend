"""Public routes: GET /v1/legal/documents[/{kind}]."""

from app.interfaces.http.v1.legal.deps import AppScopeQuery, ContainerDep, Locale
from app.interfaces.http.v1.legal.schemas import (
    LegalDocumentListOut,
    LegalDocumentOut,
    LegalKindValue,
)


async def list_documents(
    container: ContainerDep, locale: Locale, app_scope: AppScopeQuery = "global"
) -> LegalDocumentListOut:
    """The current published version of every kind of the scope (default global)."""
    documents = await container.legal.list_current.execute(app_scope)
    return LegalDocumentListOut(
        items=[LegalDocumentOut.of(d, locale) for d in documents]
    )


async def get_document(
    kind: LegalKindValue,
    container: ContainerDep,
    locale: Locale,
    app_scope: AppScopeQuery = "global",
) -> LegalDocumentOut:
    """The current published version of one kind in the scope (404 when none)."""
    document = await container.legal.get_current.execute(kind, app_scope)
    return LegalDocumentOut.of(document, locale)

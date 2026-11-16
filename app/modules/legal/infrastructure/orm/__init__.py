"""ORM models of the legal module (tables in schema ``legal``)."""

from app.modules.legal.infrastructure.orm.tables import (
    AcceptanceRow,
    LegalDocumentRow,
    PurposeConsentRow,
)

__all__ = ["AcceptanceRow", "LegalDocumentRow", "PurposeConsentRow"]

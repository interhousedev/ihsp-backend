"""SQL repository of legal documents and acceptances."""

from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.legal.domain.models import (
    Acceptance,
    DocKey,
    DocumentStatus,
    LegalDocument,
)
from app.modules.legal.infrastructure.orm.tables import (
    AcceptanceRow,
    LegalDocumentRow,
)

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

Doc = LegalDocumentRow


def to_document(row: Doc) -> LegalDocument:
    """Map a row to the domain document."""
    return LegalDocument(
        id=row.id,
        kind=row.kind,
        version=row.version,
        status=DocumentStatus(row.status),
        title=dict(row.title),
        body_markdown=dict(row.body_markdown),
        announcement=dict(row.announcement) if row.announcement else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
        published_by=row.published_by,
        app_scope=row.app_scope,
    )


class SqlLegalRepository:
    """Documents and acceptances on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session."""
        self.session = session

    async def lock_kind(self, kind: str, app_scope: str) -> None:
        """Take a transaction-scoped advisory lock for the kind and scope."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"legal:{app_scope}:{kind}"},
        )

    async def _documents(self, *where: object) -> list[LegalDocument]:
        stmt = select(Doc).order_by(Doc.app_scope, Doc.kind, Doc.version.desc())
        for clause in where:
            stmt = stmt.where(clause)  # type: ignore[arg-type]
        return [to_document(r) for r in (await self.session.scalars(stmt)).all()]

    async def list_documents(self) -> list[LegalDocument]:
        """Every version, by scope, kind, then newest version first."""
        return await self._documents()

    async def list_current(
        self, app_scopes: Collection[str] | None = None
    ) -> list[LegalDocument]:
        """The newest published version of each (kind, scope) that has one."""
        where: list[object] = [Doc.status == "published"]
        if app_scopes is not None:
            where.append(Doc.app_scope.in_(list(app_scopes)))
        newest: dict[DocKey, LegalDocument] = {}
        for document in await self._documents(*where):
            newest.setdefault((document.kind, document.app_scope), document)
        return list(newest.values())

    async def get_current(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The newest published version of the kind in the scope."""
        row = await self.session.scalar(
            select(Doc)
            .where(
                Doc.kind == kind,
                Doc.app_scope == app_scope,
                Doc.status == "published",
            )
            .order_by(Doc.version.desc())
            .limit(1)
        )
        return to_document(row) if row else None

    async def get_draft(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The draft of the kind in the scope, if any."""
        row = await self.session.scalar(
            select(Doc).where(
                Doc.kind == kind, Doc.app_scope == app_scope, Doc.status == "draft"
            )
        )
        return to_document(row) if row else None

    async def next_version(self, kind: str, app_scope: str) -> int:
        """The number after the newest version of the kind in the scope."""
        newest = await self.session.scalar(
            select(func.max(Doc.version)).where(
                Doc.kind == kind, Doc.app_scope == app_scope
            )
        )
        return (newest or 0) + 1

    async def add(self, document: LegalDocument) -> None:
        """Insert a document."""
        self.session.add(
            Doc(
                id=document.id,
                kind=document.kind,
                app_scope=document.app_scope,
                version=document.version,
                status=document.status.value,
                title=document.title,
                body_markdown=document.body_markdown,
                announcement=document.announcement,
                published_at=document.published_at,
                published_by=document.published_by,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )
        await self.session.flush()

    async def save(self, document: LegalDocument) -> None:
        """Write the editable fields and the publication of a document."""
        await self.session.execute(
            update(Doc)
            .where(Doc.id == document.id)
            .values(
                status=document.status.value,
                title=document.title,
                body_markdown=document.body_markdown,
                announcement=document.announcement,
                published_at=document.published_at,
                published_by=document.published_by,
                updated_at=document.updated_at,
            )
        )

    async def accepted_versions(self, user_id: UUID) -> dict[DocKey, set[int]]:
        """Versions the user accepted, by (kind, scope)."""
        rows = await self.session.execute(
            select(
                AcceptanceRow.kind, AcceptanceRow.app_scope, AcceptanceRow.version
            ).where(AcceptanceRow.user_id == user_id)
        )
        found: dict[DocKey, set[int]] = {}
        for kind, scope, version in rows.all():
            found.setdefault((kind, scope), set()).add(version)
        return found

    async def add_acceptances(self, acceptances: Sequence[Acceptance]) -> None:
        """Insert acceptances; one the user already gave is skipped."""
        if not acceptances:
            return
        await self.session.execute(
            insert(AcceptanceRow)
            .values(
                [
                    {
                        "id": a.id,
                        "user_id": a.user_id,
                        "kind": a.kind,
                        "app_scope": a.app_scope,
                        "version": a.version,
                        "guardian_attested": a.guardian_attested,
                        "accepted_at": a.accepted_at,
                        "ip": a.ip,
                        "user_agent": a.user_agent,
                    }
                    for a in acceptances
                ]
            )
            .on_conflict_do_nothing(constraint="uq_acceptances_user_kind_scope_version")
        )

    async def count_acceptances(self, current: dict[DocKey, int]) -> dict[DocKey, int]:
        """Distinct users that accepted the given version, by (kind, scope)."""
        counts: dict[DocKey, int] = {}
        for (kind, scope), version in current.items():
            counts[(kind, scope)] = (
                await self.session.scalar(
                    select(func.count()).where(
                        AcceptanceRow.kind == kind,
                        AcceptanceRow.app_scope == scope,
                        AcceptanceRow.version == version,
                    )
                )
                or 0
            )
        return counts

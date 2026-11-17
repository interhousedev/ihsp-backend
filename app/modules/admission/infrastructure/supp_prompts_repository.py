"""SQL repository of supplemental essay prompts."""

from uuid import UUID

from app.modules.admission.domain.supp_prompts import SuppPrompt
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.supp_prompts import SuppPromptRow
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlSuppPromptRepository:
    """Prompts of an institution, grouped by cycle."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def institution_exists(self, institution_id: UUID) -> bool:
        """Whether the catalog has the institution."""
        found = await self._s.scalar(
            select(InstitutionRow.id).where(InstitutionRow.id == institution_id)
        )
        return found is not None

    async def by_cycle(self, institution_id: UUID) -> dict[str, list[SuppPrompt]]:
        """Every cycle of the institution with its prompts in position order."""
        rows = await self._s.scalars(
            select(SuppPromptRow)
            .where(SuppPromptRow.institution_id == institution_id)
            .order_by(SuppPromptRow.cycle, SuppPromptRow.position)
        )
        out: dict[str, list[SuppPrompt]] = {}
        for r in rows:
            out.setdefault(r.cycle, []).append(
                SuppPrompt(
                    position=r.position,
                    prompt=r.prompt,
                    word_limit=r.word_limit,
                    required=r.required,
                    source_url=r.source_url,
                )
            )
        return out

    async def replace(
        self, institution_id: UUID, cycle: str, prompts: list[SuppPrompt]
    ) -> None:
        """Drop the prompts of the cycle and store the given ones."""
        await self._s.execute(
            delete(SuppPromptRow).where(
                SuppPromptRow.institution_id == institution_id,
                SuppPromptRow.cycle == cycle,
            )
        )
        await self._s.flush()
        self._s.add_all(
            SuppPromptRow(
                id=new_id(),
                institution_id=institution_id,
                cycle=cycle,
                position=p.position,
                prompt=p.prompt,
                word_limit=p.word_limit,
                required=p.required,
                source_url=p.source_url,
            )
            for p in prompts
        )
        await self._s.flush()

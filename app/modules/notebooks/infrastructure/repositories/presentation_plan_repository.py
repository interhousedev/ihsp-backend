"""SQL repository of presentation plans (PLAN)."""

from uuid import UUID

from app.modules.notebooks.domain.presentation_plan import (
    PlanSlide,
    PlanStatus,
    PresentationPlan,
)
from app.modules.notebooks.infrastructure.orm.presentation_plan import (
    PresentationPlan as Row,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_plan(row: Row) -> PresentationPlan:
    return PresentationPlan(
        id=row.id,
        notebook_id=row.notebook_id,
        owner_id=row.owner_id,
        title=row.title,
        slides=[PlanSlide.model_validate(item) for item in row.slides],
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=PlanStatus(row.status),
        prompt=row.prompt,
        source_ids=list(row.source_ids),
        format=row.format,
        artifact_id=row.artifact_id,
    )


def _slides(plan: PresentationPlan) -> list[dict[str, object]]:
    return [slide.model_dump(mode="json") for slide in plan.slides]


class SqlPresentationPlanRepository:
    """Presentation plans on the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the session."""
        self.session = session

    async def add(self, plan: PresentationPlan) -> None:
        """Insert a new plan."""
        self.session.add(
            Row(
                id=plan.id,
                notebook_id=plan.notebook_id,
                owner_id=plan.owner_id,
                title=plan.title,
                slides=_slides(plan),
                status=plan.status.value,
                prompt=plan.prompt,
                source_ids=list(plan.source_ids),
                format=plan.format,
                artifact_id=plan.artifact_id,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
            )
        )
        await self.session.flush()

    async def get(self, plan_id: UUID) -> PresentationPlan | None:
        """The plan with this id, if any."""
        row = await self.session.get(Row, plan_id)
        return _to_plan(row) if row is not None else None

    async def get_for_update(self, plan_id: UUID) -> PresentationPlan | None:
        """The plan with this id, locked for the transaction."""
        stmt = select(Row).where(Row.id == plan_id).with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_plan(row) if row is not None else None

    async def save(self, plan: PresentationPlan) -> None:
        """Store the changed fields of a plan."""
        row = await self.session.get(Row, plan.id)
        if row is None:
            return
        row.title = plan.title
        row.slides = _slides(plan)
        row.status = plan.status.value
        row.artifact_id = plan.artifact_id
        row.updated_at = plan.updated_at
        await self.session.flush()

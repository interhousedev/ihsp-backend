"""SQL repository of dashboard layouts."""

from uuid import UUID

from app.modules.dashboard.domain.layout import Layout
from app.modules.dashboard.domain.widget import Widget
from app.modules.dashboard.infrastructure.orm.layout import DashboardLayout

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlLayoutRepository:
    """Layouts in `dashboard.layouts`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the open session."""
        self._session = session

    async def get(self, user_id: UUID, *, for_update: bool = False) -> Layout | None:
        """Return the stored layout; lock the row when asked."""
        stmt = select(DashboardLayout).where(DashboardLayout.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return Layout(
            user_id=row.user_id,
            version=int(row.version),
            widgets=[Widget.model_validate(w) for w in row.widgets],
        )

    async def save(self, layout: Layout) -> None:
        """Insert or replace the layout."""
        data = [w.model_dump(mode="json") for w in layout.widgets]
        row = await self._session.get(DashboardLayout, layout.user_id)
        if row is None:
            self._session.add(
                DashboardLayout(
                    user_id=layout.user_id, version=layout.version, widgets=data
                )
            )
        else:
            row.version = layout.version
            row.widgets = data
        await self._session.flush()

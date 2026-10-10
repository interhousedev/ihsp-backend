"""GET /v1/admin/insights."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_insights import reader
from app.interfaces.http.v1.admin_insights.schemas import (
    InsightsResponse,
    MarksInsights,
    UsageInsights,
)
from app.interfaces.http.v1.admin_insights.series import (
    DAYS,
    fill_days,
    mark_histogram,
)
from app.shared.actor import Actor, Role
from app.shared.clock import local_today

from fastapi import Depends


async def get_insights(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> InsightsResponse:
    """System health, daily usage and the marks histogram for the report pages."""
    now = container.clock.now()
    since = reader.local_midnight_days_ago(now, DAYS)
    today = local_today(container.clock)
    return InsightsResponse(
        generated_at=now,
        system=await reader.system_health(container, now),
        usage=UsageInsights(
            sign_ins=fill_days(await reader.sign_ins_by_day(container, since), today),
            ai_tokens=fill_days(await reader.ai_tokens_by_day(container, since), today),
            storage=await reader.storage(container),
        ),
        marks=MarksInsights(
            distribution=mark_histogram(await reader.mark_counts(container))
        ),
    )

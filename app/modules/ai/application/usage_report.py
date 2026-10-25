"""Use case: the usage report of the admin page (tokens, calls, cost; admin only)."""

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.ai.domain.usage import GroupTotals, Totals, UserTotals
from app.modules.ai.ports.usage import UsageReader
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory

TASHKENT = ZoneInfo("Asia/Tashkent")
MAX_RANGE_DAYS = 400
DEFAULT_RANGE_DAYS = 30
TOP_USERS = 20
GroupBy = Literal["day", "task", "model", "role", "feature", "user"]


class UsageRangeInvalidError(ValidationFailedError):
    """The range is backwards or longer than the report allows."""

    code = "ai/usage-range-invalid"
    message_key = "ai-usage-range-invalid"


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One group of the report: its totals and the cost of each feature."""

    key: str
    totals: Totals
    cost_by_feature: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TopUser:
    """A user with the largest cost in the range."""

    user_id: UUID
    name: str
    login: str | None
    role: str
    totals: Totals


@dataclass(frozen=True, slots=True)
class MonthView:
    """Month to date and the projection to the end of the month (micro-dollars)."""

    month: str
    cost_micro: int
    projected_micro: int
    days_elapsed: int
    days_in_month: int


@dataclass(frozen=True, slots=True)
class UsageReportView:
    """The whole report for one range and grouping."""

    from_day: date
    to_day: date
    group_by: str
    generated_at: datetime
    totals: Totals
    rows: list[UsageRow]
    top_users: list[TopUser]
    month: MonthView
    today: Totals


class UsageReport:
    """Aggregates the ledger for the admin page."""

    def __init__(
        self, *, reader: UsageReader, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Keep the reader, the directory of names and the clock."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        from_day: date | None = None,
        to_day: date | None = None,
        group_by: GroupBy = "day",
    ) -> UsageReportView:
        """The report of [from_day, to_day] (Tashkent dates), by the given grouping."""
        actor.require(Role.ADMIN)
        today = local_today(self.clock)
        end = to_day or today
        start = from_day or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        if start > end or (end - start).days >= MAX_RANGE_DAYS:
            raise UsageRangeInvalidError(params={"max_days": MAX_RANGE_DAYS})
        start_at = _midnight(start)
        end_at = _midnight(end + timedelta(days=1))

        totals = await self.reader.totals(start_at, end_at)
        groups = await self.reader.grouped(start_at, end_at, group_by)
        rows = _rows(groups, group_by, start, end)
        top = await self.reader.top_users(start_at, end_at, TOP_USERS)
        top_users = await self._top_users(top)

        month_start = date(today.year, today.month, 1)
        month_cost = await self.reader.totals(
            _midnight(month_start), _midnight(today + timedelta(days=1))
        )
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        projected = month_cost.cost_micro * days_in_month // today.day
        today_totals = await self.reader.totals(
            _midnight(today), _midnight(today + timedelta(days=1))
        )
        return UsageReportView(
            from_day=start,
            to_day=end,
            group_by=group_by,
            generated_at=self.clock.now(),
            totals=totals,
            rows=rows,
            top_users=top_users,
            month=MonthView(
                month=f"{today.year:04d}-{today.month:02d}",
                cost_micro=month_cost.cost_micro,
                projected_micro=projected,
                days_elapsed=today.day,
                days_in_month=days_in_month,
            ),
            today=today_totals,
        )

    async def _top_users(self, top: list[UserTotals]) -> list[TopUser]:
        if not top:
            return []
        users = await self.identity.get_users([row.user_id for row in top])
        result: list[TopUser] = []
        for row in top:
            user = users.get(row.user_id)
            name = f"{user.first_name} {user.last_name}".strip() if user else ""
            result.append(
                TopUser(
                    user_id=row.user_id,
                    name=name or str(row.user_id),
                    login=user.login if user else None,
                    role=row.role,
                    totals=row.totals,
                )
            )
        return result


def _rows(
    groups: list[GroupTotals], group_by: str, start: date, end: date
) -> list[UsageRow]:
    totals: dict[str, Totals] = {}
    features: dict[str, dict[str, int]] = {}
    for group in groups:
        totals[group.key] = _add(totals.get(group.key), group.totals)
        features.setdefault(group.key, {})[group.feature] = group.totals.cost_micro
    if group_by == "day":
        # A chart needs every day of the range, also the ones without calls.
        for offset in range((end - start).days + 1):
            key = (start + timedelta(days=offset)).isoformat()
            totals.setdefault(key, Totals())
            features.setdefault(key, {})
    return [
        UsageRow(key=key, totals=totals[key], cost_by_feature=features.get(key, {}))
        for key in sorted(totals)
    ]


def _add(left: Totals | None, right: Totals) -> Totals:
    if left is None:
        return right
    return Totals(
        tokens_in=left.tokens_in + right.tokens_in,
        tokens_out=left.tokens_out + right.tokens_out,
        cached=left.cached + right.cached,
        calls=left.calls + right.calls,
        failed=left.failed + right.failed,
        cost_micro=left.cost_micro + right.cost_micro,
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=TASHKENT).astimezone(UTC)

"""Request and response models of the Limits & usage routes (Administration only)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admin.application.limit_admin import ExtensionRow, LimitRow
from app.modules.admin.domain.limits import (
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    NOTE_MAX_LENGTH,
    ExtensionTerms,
)
from app.modules.ai.application.prompt_registry import (
    PromptVersionStats,
    SlotDetail,
    SlotStatus,
)
from app.modules.ai.application.usage_report import TopUser, UsageReportView
from app.modules.ai.domain.prompt_registry import MAX_PROMPT_CHARS, PromptVersion
from app.modules.ai.domain.usage import Totals
from app.shared.ai_access import AiAccess
from app.shared.contracts.identity import UserRef

from pydantic import BaseModel, ConfigDict, Field

GroupBy = Literal["day", "task", "model", "role", "feature", "user"]


def _usd(micro: int) -> float:
    return round(micro / 1_000_000, 6)


class LimitItem(BaseModel):
    """One editable limit: its value in force, its environment value and its bounds."""

    key: str
    group: str
    label_key: str
    unit: str = Field(description="tokens, count, steps, hours or bytes.")
    period: str | None = Field(
        description="session, day, week, minute or hour; null if standing."
    )
    minimum: int
    maximum: int
    unlimitable: bool = Field(
        description="True when -1 (no cap, shown as unlimited) is a valid value."
    )
    value: int | None = Field(description="The value in force; -1 means no cap.")
    default: int | None = Field(
        description="The environment's value; a reset gives it back."
    )
    overridden: bool
    description: str = Field(description="The settings' description (English).")

    @classmethod
    def of(cls, row: LimitRow) -> "LimitItem":
        """Build from the application row."""
        spec = row.spec
        return cls(
            key=spec.key,
            group=spec.group,
            label_key=f"admin-limit-{spec.key.replace('_', '-')}",
            unit=spec.unit,
            period=spec.period,
            minimum=spec.minimum,
            maximum=spec.maximum,
            unlimitable=spec.unlimitable,
            value=row.value,
            default=row.default,
            overridden=row.overridden,
            description=spec.description,
        )


class LimitsResponse(BaseModel):
    """GET and PUT /v1/admin/ai/limits."""

    limits: list[LimitItem]

    @classmethod
    def of(cls, rows: list[LimitRow]) -> "LimitsResponse":
        """Build from the application rows."""
        return cls(limits=[LimitItem.of(row) for row in rows])


class LimitsBody(BaseModel):
    """PUT /v1/admin/ai/limits: the limits to change; null resets one to its default."""

    model_config = ConfigDict(extra="forbid")

    limits: dict[str, int | None] = Field(min_length=1)


class TotalsOut(BaseModel):
    """Sums of the ledger: tokens, calls, failed calls and cost in US dollars."""

    tokens_in: int
    tokens_out: int
    cached: int
    calls: int
    failed: int
    cost_usd: float

    @classmethod
    def of(cls, totals: Totals) -> "TotalsOut":
        """Build from the totals."""
        return cls(
            tokens_in=totals.tokens_in,
            tokens_out=totals.tokens_out,
            cached=totals.cached,
            calls=totals.calls,
            failed=totals.failed,
            cost_usd=_usd(totals.cost_micro),
        )


class UsageRowOut(TotalsOut):
    """One group of the report (a day, a task, a model, ...)."""

    key: str
    cost_by_feature: dict[str, float]

    @classmethod
    def of_row(cls, row: Any) -> "UsageRowOut":
        """Build from an application row."""
        totals = TotalsOut.of(row.totals)
        return cls(
            **totals.model_dump(),
            key=row.key,
            cost_by_feature={
                name: _usd(micro) for name, micro in row.cost_by_feature.items()
            },
        )


class TopUserOut(TotalsOut):
    """A user with the largest cost in the range."""

    user_id: UUID
    name: str
    login: str | None
    role: str

    @classmethod
    def of_user(cls, user: TopUser) -> "TopUserOut":
        """Build from the application user."""
        totals = TotalsOut.of(user.totals)
        return cls(
            **totals.model_dump(),
            user_id=user.user_id,
            name=user.name,
            login=user.login,
            role=user.role,
        )


class MonthOut(BaseModel):
    """Month to date and the projection to the end of the month."""

    month: str
    cost_usd: float
    projected_usd: float
    days_elapsed: int
    days_in_month: int


class UsageResponse(BaseModel):
    """GET /v1/admin/ai/usage."""

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    group_by: GroupBy
    generated_at: datetime
    totals: TotalsOut
    rows: list[UsageRowOut]
    top_users: list[TopUserOut]
    month: MonthOut
    today: TotalsOut

    @classmethod
    def of(cls, view: UsageReportView) -> "UsageResponse":
        """Build from the report."""
        month = view.month
        return cls(
            from_=view.from_day,
            to=view.to_day,
            group_by=view.group_by,
            generated_at=view.generated_at,
            totals=TotalsOut.of(view.totals),
            rows=[UsageRowOut.of_row(row) for row in view.rows],
            top_users=[TopUserOut.of_user(user) for user in view.top_users],
            month=MonthOut(
                month=month.month,
                cost_usd=_usd(month.cost_micro),
                projected_usd=_usd(month.projected_micro),
                days_elapsed=month.days_elapsed,
                days_in_month=month.days_in_month,
            ),
            today=TotalsOut.of(view.today),
        )


class ExtensionBody(BaseModel):
    """PUT /v1/admin/ai/limit-extensions/{user_id}: create or replace an extension."""

    model_config = ConfigDict(extra="forbid")

    multiplier: int | None = Field(default=None, ge=MULTIPLIER_MIN, le=MULTIPLIER_MAX)
    values: dict[str, int] = Field(default_factory=dict)
    expires_on: date | None = None
    note: str = Field(default="", max_length=NOTE_MAX_LENGTH)

    def terms(self) -> ExtensionTerms:
        """The domain terms of the body."""
        return ExtensionTerms(
            multiplier=self.multiplier,
            values=dict(self.values),
            expires_on=self.expires_on,
            note=self.note,
        )


class ExtensionOut(BaseModel):
    """One extension with the student it is for."""

    user_id: UUID
    user_name: str
    login: str | None
    multiplier: int | None
    values: dict[str, int]
    expires_on: date | None
    note: str
    active: bool
    updated_at: datetime

    @classmethod
    def of(cls, row: ExtensionRow) -> "ExtensionOut":
        """Build from the application row."""
        record = row.record
        return cls(
            user_id=record.user_id,
            user_name=_name(row.user, record.user_id),
            login=row.user.login if row.user else None,
            multiplier=record.terms.multiplier,
            values=dict(record.terms.values),
            expires_on=record.terms.expires_on,
            note=record.terms.note,
            active=row.active,
            updated_at=record.updated_at,
        )


class ExtensionsResponse(BaseModel):
    """GET /v1/admin/ai/limit-extensions."""

    items: list[ExtensionOut]


class StudentOut(BaseModel):
    """A student found by name or login (for the extension picker)."""

    id: UUID
    name: str
    login: str | None

    @classmethod
    def of(cls, user: UserRef) -> "StudentOut":
        """Build from the identity reference."""
        return cls(id=user.id, name=_name(user, user.id), login=user.login)


class StudentsResponse(BaseModel):
    """GET /v1/admin/ai/limit-extensions/students."""

    items: list[StudentOut]


class AiAccessBody(BaseModel):
    """PUT /v1/admin/ai/users/{user_id}/access: both flags, true revokes the scope."""

    model_config = ConfigDict(extra="forbid")

    ai_chat_blocked: bool
    ai_notebooks_blocked: bool


class AiAccessOut(BaseModel):
    """The AI scopes revoked from one user."""

    user_id: UUID
    ai_chat_blocked: bool
    ai_notebooks_blocked: bool

    @classmethod
    def of(cls, user_id: UUID, access: AiAccess) -> "AiAccessOut":
        """Build from the application value."""
        return cls(
            user_id=user_id,
            ai_chat_blocked=access.chat_blocked,
            ai_notebooks_blocked=access.notebooks_blocked,
        )


def _name(user: UserRef | None, user_id: UUID) -> str:
    if user is None:
        return str(user_id)
    return f"{user.first_name} {user.last_name}".strip() or str(user_id)


class PromptVersionOut(BaseModel):
    """One stored text of a prompt slot; `locale` "" means every locale."""

    id: UUID
    version: int
    locale: str
    text: str
    hash: str
    active: bool
    created_at: datetime
    created_by: UUID | None
    note: str

    @classmethod
    def of(cls, version: PromptVersion) -> "PromptVersionOut":
        """From the domain version."""
        return cls(
            id=version.id,
            version=version.version,
            locale=version.locale,
            text=version.text,
            hash=version.hash,
            active=version.active,
            created_at=version.created_at,
            created_by=version.created_by,
            note=version.note,
        )


class PromptActiveOut(BaseModel):
    """The active override of a locale."""

    locale: str
    version: int
    hash: str


class PromptSlotOut(BaseModel):
    """An editable piece of a task's prompt, overridden or built-in."""

    task: str
    name: str
    summary: str
    template: bool
    placeholders: list[str]
    overridden: bool
    active: list[PromptActiveOut]

    @classmethod
    def of(cls, status: SlotStatus) -> "PromptSlotOut":
        """From the slot and its active versions."""
        slot = status.slot
        return cls(
            task=slot.task,
            name=slot.name,
            summary=slot.summary,
            template=slot.template,
            placeholders=sorted(slot.fields),
            overridden=bool(status.active),
            active=[
                PromptActiveOut(locale=v.locale, version=v.version, hash=v.hash)
                for v in status.active
            ],
        )


class PromptSlotsResponse(BaseModel):
    """Every editable prompt slot."""

    items: list[PromptSlotOut]


class PromptDetailOut(BaseModel):
    """A slot: the text in force for the locale, the built-in text and the history."""

    task: str
    name: str
    summary: str
    template: bool
    placeholders: list[str]
    locale: str
    text: str
    version: int = Field(description="The version in force; 0 is the built-in text.")
    hash: str
    builtin: str
    versions: list[PromptVersionOut]

    @classmethod
    def of(cls, detail: SlotDetail, locale: str) -> "PromptDetailOut":
        """From the slot detail."""
        slot = detail.slot
        return cls(
            task=slot.task,
            name=slot.name,
            summary=slot.summary,
            template=slot.template,
            placeholders=sorted(slot.fields),
            locale=locale,
            text=detail.current.text,
            version=detail.current.version,
            hash=detail.current.hash,
            builtin=slot.builtin,
            versions=[PromptVersionOut.of(v) for v in detail.versions],
        )


class PromptBody(BaseModel):
    """A new version of a slot's text; `locale` "" applies to every locale."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    locale: Literal["", "uz", "ru", "en"] = ""
    note: str = Field(default="", max_length=500)


class PromptStatsOut(BaseModel):
    """How one prompt version of a task did in the period (0 = built-in)."""

    task: str
    version: int
    calls: int
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    ratings: int
    rating_average: float | None = Field(
        description="Mean of the ratings: thumbs up 1, down -1."
    )

    @classmethod
    def of(cls, row: PromptVersionStats) -> "PromptStatsOut":
        """From the analytics row."""
        return cls(
            task=row.task,
            version=row.version,
            calls=row.calls,
            error_rate=row.error_rate,
            p50_ms=row.p50_ms,
            p95_ms=row.p95_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_usd=_usd(row.cost_micro),
            ratings=row.ratings,
            rating_average=row.rating_average,
        )


class PromptAnalyticsResponse(BaseModel):
    """The figures per task and prompt version for [from, to] (Tashkent dates)."""

    from_day: date = Field(serialization_alias="from")
    to_day: date = Field(serialization_alias="to")
    items: list[PromptStatsOut]

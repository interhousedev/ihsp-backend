"""`GET /v1/admission/config` and `GET /v1/admission/me`."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_args

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.tasks import HORIZONS
from app.modules.admission.domain import questions as q
from app.modules.admission.domain.access import IneligibleReason
from app.modules.admission.domain.chooser import (
    BINDING_ROUNDS,
    UNRESOLVED_AFFORDABILITY,
)
from app.modules.admission.domain.countries import COUNTRIES
from app.modules.admission.domain.documents import (
    MILESTONE_KINDS,
    REJECT_REASON_CODES,
    REMINDER_CHANNELS,
    REMINDER_OFFSETS,
    UPLOAD_MIME,
    DeadlineStatus,
)
from app.modules.admission.domain.entitlement import ActorKind
from app.modules.admission.domain.goal_plan import GoalStatus
from app.modules.admission.domain.items import (
    ACTIVITY_CATEGORIES,
    GRADES,
    MAX_ACTIVITIES,
    MAX_DRAFTS,
    MAX_HONORS,
    RECOGNITION_LEVELS,
    TIMINGS,
)
from app.modules.admission.domain.permissions import BUILTIN_ROLES, BuiltinRole
from app.modules.admission.domain.profile import Stage
from app.modules.admission.domain.runtime_settings import (
    ESTIMATES_STUDENT_VISIBLE,
    WELLBEING_QUESTIONS,
)
from app.modules.admission.domain.tasks import LINK_KINDS as TASK_LINK_KINDS
from app.modules.admission.domain.tasks import PRIORITIES as TASK_PRIORITIES
from app.modules.admission.domain.tasks import SOURCES as TASK_SOURCES
from app.modules.admission.domain.tasks import STATUSES as TASK_STATUSES
from app.modules.admission.domain.workflow import (
    CONFIDENTIAL_KINDS,
    AffordabilityStatus,
    DocumentKind,
    Label,
    ListStatus,
    Round,
)
from app.settings_admission import AdmissionSettings
from app.shared.honor_categories import HONOR_CATEGORIES
from app.shared.limits import LimitsProvider

OPTION_LISTS: dict[str, tuple[str, ...]] = {
    "yes_no_applying": q.YES_NO_APPLYING,
    "grades": q.GRADES,
    "archetypes": q.ARCHETYPES,
    "study_levels": q.STUDY_LEVELS,
    "languages": q.LANGUAGES,
    "city_types": q.CITY_TYPES,
    "sizes": q.SIZES,
    "climates": q.CLIMATES,
    "distances": q.DISTANCES,
    "work_visa": q.WORK_VISA,
    "budget_bands": q.BUDGET_BANDS,
    "aid_need": q.AID_NEED,
    "scholarship_basis": q.SCHOLARSHIP_BASIS,
    "fee_waiver": q.FEE_WAIVER,
    "facilities": q.FACILITIES,
    "genders": q.GENDERS,
    "english_tests": q.ENGLISH_TESTS,
    "sat_act": q.SAT_ACT,
    "other_tests": q.OTHER_TESTS,
    "subjects": q.SUBJECTS,
    "upload_mime": UPLOAD_MIME,
}
"""Option ids of the setup wizard; the web holds their texts."""


@dataclass(frozen=True, slots=True)
class WorkflowOptions:
    """Ids of the document, deadline, list and plan vocabularies (no labels)."""

    document_kinds: tuple[tuple[str, bool], ...]
    reject_reasons: tuple[str, ...]
    reminder_offsets: tuple[int, ...]
    reminder_channels: tuple[str, ...]
    deadline_statuses: tuple[str, ...]
    rounds: tuple[tuple[str, bool], ...]
    list_statuses: tuple[str, ...]
    buckets: tuple[str, ...]
    milestone_kinds: tuple[str, ...]
    milestone_statuses: tuple[str, ...]
    affordability_statuses: tuple[str, ...]
    affordability_ack_statuses: tuple[str, ...]
    task_statuses: tuple[str, ...]
    task_priorities: tuple[str, ...]
    task_sources: tuple[str, ...]
    task_link_kinds: tuple[str, ...]
    task_horizons: tuple[str, ...]


WORKFLOW_OPTIONS = WorkflowOptions(
    document_kinds=tuple((k, k in CONFIDENTIAL_KINDS) for k in get_args(DocumentKind)),
    reject_reasons=REJECT_REASON_CODES,
    reminder_offsets=REMINDER_OFFSETS,
    reminder_channels=REMINDER_CHANNELS,
    deadline_statuses=get_args(DeadlineStatus),
    rounds=tuple((r, r in BINDING_ROUNDS) for r in get_args(Round)),
    list_statuses=get_args(ListStatus),
    buckets=get_args(Label),
    milestone_kinds=MILESTONE_KINDS,
    milestone_statuses=get_args(GoalStatus),
    affordability_statuses=get_args(AffordabilityStatus),
    affordability_ack_statuses=UNRESOLVED_AFFORDABILITY,
    task_statuses=TASK_STATUSES,
    task_priorities=TASK_PRIORITIES,
    task_sources=TASK_SOURCES,
    task_link_kinds=TASK_LINK_KINDS,
    task_horizons=HORIZONS,
)


@dataclass(frozen=True, slots=True)
class AdmissionConfig:
    """Everything the admission web app needs before the first screen."""

    question_set: str
    questions: tuple[q.Question, ...]
    options: dict[str, tuple[str, ...]]
    stages: tuple[str, ...]
    limits: dict[str, int]
    estimates_student_visible: bool
    wellbeing_questions_enabled: bool
    sub_roles: tuple[BuiltinRole, ...]
    pickup_location: dict[str, str] | None
    item_caps: dict[str, int]
    school_grades: tuple[int, ...]
    workflow: WorkflowOptions


class GetConfig:
    """Builds the config from the environment and the runtime settings."""

    def __init__(
        self,
        settings: AdmissionSettings,
        runtime: RuntimeSettingsService,
        limits: LimitsProvider,
        study_fields: Callable[[], tuple[str, ...]] = lambda: (),
    ) -> None:
        """Keep the environment settings, the runtime snapshot and the limits."""
        self._study_fields = study_fields
        self._settings = settings
        self._limits = limits
        self._runtime = runtime

    async def estimates_visible(self, ctx: AdmissionContext) -> bool:
        """Whether the caller sees estimates: staff always, students per setting."""
        if ctx.admission.is_staff:
            return True
        rs = await self._runtime.get()
        return bool(
            rs.get(ESTIMATES_STUDENT_VISIBLE, self._settings.estimates_student_visible)
        )

    async def execute(self) -> AdmissionConfig:
        """Return the config; the wellbeing section is hidden unless enabled."""
        rs = await self._runtime.get()
        wellbeing = bool(rs.get(WELLBEING_QUESTIONS, False))
        questions = tuple(
            x
            for x in q.QUESTIONS
            if x.enabled and (wellbeing or x.section != "wellbeing")
        )
        return AdmissionConfig(
            question_set=q.QUESTION_SET_VERSION,
            questions=questions,
            options={
                **OPTION_LISTS,
                "countries": COUNTRIES,
                "fields": self._study_fields(),
                "activity_categories": ACTIVITY_CATEGORIES,
                "recognition_levels": RECOGNITION_LEVELS,
                "honor_categories": HONOR_CATEGORIES,
                "activity_timing": TIMINGS,
                "item_grades": tuple(str(g) for g in GRADES),
            },
            stages=get_args(Stage),
            limits={
                name.removeprefix("admit_"): value
                for name, value in (await self._limits.current()).model_dump().items()
                if name.startswith("admit_")
            },
            estimates_student_visible=bool(
                rs.get(
                    ESTIMATES_STUDENT_VISIBLE, self._settings.estimates_student_visible
                )
            ),
            wellbeing_questions_enabled=wellbeing,
            sub_roles=BUILTIN_ROLES,
            pickup_location=rs.pickup_location(),
            item_caps={
                "activities": MAX_ACTIVITIES,
                "honors": MAX_HONORS,
                "drafts": MAX_DRAFTS,
            },
            workflow=WORKFLOW_OPTIONS,
            school_grades=rs.school_grades(self._settings.eligible_grades),
        )


@dataclass(frozen=True, slots=True)
class AdmissionMe:
    """What the caller may do in the admission app."""

    kind: ActorKind
    may_enter: bool
    ineligible_reason: IneligibleReason | None
    grade: int | None
    entitlement_kind: str | None
    staff_roles: tuple[str, ...]
    sub_roles: tuple[dict[str, Any], ...]


def get_me(ctx: AdmissionContext, now: dt.datetime) -> AdmissionMe:
    """Describe the caller; only assignments in force at `now` are listed."""
    adm = ctx.admission
    return AdmissionMe(
        kind=adm.kind,
        may_enter=adm.may_enter,
        ineligible_reason=adm.ineligible_reason(ctx.grade),
        grade=ctx.grade,
        entitlement_kind=adm.entitlement.kind if adm.entitlement else None,
        staff_roles=tuple(sorted(r.value for r in adm.staff_roles)),
        sub_roles=tuple(
            {
                "assignment_id": a.id,
                "role_id": a.role.id,
                "kind": a.role.kind,
                "name": a.role.name,
                "name_i18n": a.role.name_i18n,
                "scope_kind": a.scope_kind,
                "scope_ref": a.scope_ref,
                "expires_at": a.expires_at,
            }
            for a in ctx.assignments
            if a.active_at(now)
        ),
    )

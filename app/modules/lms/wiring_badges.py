"""Composition of badge authoring, preview, backfill and the AI draft."""

from dataclasses import dataclass

from app.modules.lms.application.badge_authoring import (
    CreateBadgeFromRule,
    CreateBadgeFromTemplate,
    CreatePlatformBadge,
    DraftBadge,
    ListBadgeTemplates,
    PreviewBadge,
    PreviewPlatformBadge,
    UpdateBadge,
)
from app.modules.lms.application.badge_awarding import BackfillBadge
from app.modules.lms.application.engagement.level_access import (
    AuditLevelEvents,
    CourseEditGate,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.infrastructure.badge_store import (
    SqlAwardStore,
    SqlBadgeStore,
    SqlEnrolmentFacts,
    SqlPlatformFacts,
    TaskBackfillQueue,
)
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class BadgeAuthoringServices:
    """The badge v2 use cases (`container.lms.badge_authoring`)."""

    store: SqlBadgeStore
    templates: ListBadgeTemplates
    create_from_template: CreateBadgeFromTemplate
    create_from_rule: CreateBadgeFromRule
    create_platform: CreatePlatformBadge
    update: UpdateBadge
    preview: PreviewBadge
    preview_platform: PreviewPlatformBadge
    draft: DraftBadge
    backfill: BackfillBadge


def build_badge_authoring(
    deps: ModuleDeps, uow_factory: UowFactory
) -> BadgeAuthoringServices:
    """Return the badge services over the lms schema."""
    store = SqlBadgeStore(deps.sessionmaker)
    access = CourseEditGate(uow_factory)
    audit = AuditLevelEvents(uow_factory)
    queue = TaskBackfillQueue(deps.kicker)
    facts = SqlEnrolmentFacts(uow_factory, deps.sessionmaker)
    return BadgeAuthoringServices(
        store=store,
        templates=ListBadgeTemplates(),
        create_from_template=CreateBadgeFromTemplate(store, audit, queue, access),
        create_from_rule=CreateBadgeFromRule(store, audit, queue, access),
        create_platform=CreatePlatformBadge(store, audit, queue),
        update=UpdateBadge(store, audit, queue, access, deps.clock),
        preview=PreviewBadge(facts, access),
        preview_platform=PreviewPlatformBadge(SqlPlatformFacts(deps.sessionmaker)),
        draft=DraftBadge(access),
        backfill=BackfillBadge(
            store,
            facts,
            SqlAwardStore(uow_factory),
            queue,
            platform_facts=SqlPlatformFacts(deps.sessionmaker),
        ),
    )

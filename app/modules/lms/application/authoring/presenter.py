"""Builds the read models of the authoring API from entities."""

from collections.abc import Iterable, Sequence
from typing import Literal
from uuid import UUID

from app.modules.lms.application.authoring.pending_loader import (
    PendingContext,
    load_pending,
)
from app.modules.lms.application.authoring.views import (
    CourseDraftView,
    CourseStaffItemView,
    OutlineSectionView,
    OutlineStepView,
    PendingChangesView,
    PendingStepView,
    PersonRefView,
    RevisionItemView,
    StepDraftView,
    VersionChangesView,
    VersionItemView,
)
from app.modules.lms.domain.authoring.entities import (
    Course,
    CourseStep,
    CourseVersion,
    StaffMember,
    StepRevision,
)
from app.modules.lms.domain.authoring.enums import StepChange
from app.modules.lms.domain.authoring.manifest import ManifestSection
from app.modules.lms.domain.authoring.pending import Pending
from app.modules.lms.domain.authoring.permissions import (
    EDIT,
    MANAGE_STAFF,
    CourseAccess,
)
from app.modules.lms.domain.step_content import StepContent
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.contracts.identity import IdentityDirectory

Badge = Literal["new", "changed", "removed", "mcp", "ai"]


class Presenter:
    """Turns entities into the JSON-shaped views of the API contract."""

    def __init__(self, identity: IdentityDirectory) -> None:
        """Store the identity directory used to name people."""
        self.identity = identity

    # - - - People - - -

    async def people(self, user_ids: Iterable[UUID]) -> dict[UUID, PersonRefView]:
        """Return `PersonRef`s for the users; unknown users get empty names."""
        wanted = list(set(user_ids))
        users = await self.identity.get_users(wanted) if wanted else {}
        return {
            uid: (
                PersonRefView(
                    id=uid,
                    first_name=users[uid].first_name,
                    last_name=users[uid].last_name,
                )
                if uid in users
                else PersonRefView(id=uid, first_name="", last_name="")
            )
            for uid in wanted
        }

    # - - - Course and outline - - -

    async def course_draft(
        self, uow: AuthoringUnitOfWork, course: Course, access: CourseAccess
    ) -> CourseDraftView:
        """Build `CourseDraft` with badges, pending count and the actor's rights."""
        context = await load_pending(uow, course)
        show_code = access.can(EDIT) or access.can(MANAGE_STAFF)
        meta = course.draft_meta
        return CourseDraftView(
            id=course.id,
            slug=course.slug,
            title=meta.get("title", course.title),
            description=meta.get("description", course.description),
            visibility=course.visibility.value,
            status=course.status.value,
            invite_code=course.invite_code if show_code else None,
            lock_version=course.lock_version,
            draft_seq=course.draft_seq,
            outline=self.draft_outline(course, context),
            pending_count=context.pending.count,
            live_version=context.live_version.number if context.live_version else None,
            my_permissions=access.permissions,
        )

    def draft_outline(
        self, course: Course, context: PendingContext
    ) -> list[OutlineSectionView]:
        """Draft outline with badges; removed steps appear in their old section."""
        badges = _badges(context.pending)
        ghosts: dict[str, list[OutlineStepView]] = {}
        in_outline = {
            s for sec in course.draft_outline["sections"] for s in sec["steps"]
        }
        for entry in context.manifest:
            if str(entry.step_id) not in in_outline:
                ghosts.setdefault(entry.section_id, []).append(
                    OutlineStepView(
                        step_id=entry.step_id, title=entry.title, badge="removed"
                    )
                )
        sections: list[OutlineSectionView] = []
        for section in course.draft_outline["sections"]:
            steps = [
                OutlineStepView(
                    step_id=UUID(raw),
                    title=context.steps[UUID(raw)].title,
                    badge=badges.get(UUID(raw)),
                )
                for raw in section["steps"]
                if UUID(raw) in context.steps
            ]
            steps.extend(ghosts.get(section["id"], []))
            sections.append(
                OutlineSectionView(
                    id=section["id"], title=section["title"], steps=steps
                )
            )
        return sections

    def manifest_outline(
        self, sections: Sequence[ManifestSection]
    ) -> list[OutlineSectionView]:
        """Outline of a published version (no badges)."""
        return [
            OutlineSectionView(
                id=section.id,
                title=section.title,
                steps=[
                    OutlineStepView(step_id=s.step_id, title=s.title)
                    for s in section.steps
                ],
            )
            for section in sections
        ]

    # - - - Steps - - -

    async def step_draft(self, step: CourseStep) -> StepDraftView:
        """Build `StepDraft` for a step."""
        people = await self.people(
            [step.draft_updated_by] if step.draft_updated_by else []
        )
        author = people.get(step.draft_updated_by) if step.draft_updated_by else None
        return StepDraftView(
            step_id=step.id,
            course_id=step.course_id,
            content=StepContent.model_validate(step.draft),
            lock_version=step.lock_version,
            status=_step_status(step),
            updated_via=step.draft_updated_via.value,
            updated_by=author,
            updated_at=step.draft_updated_at,
        )

    async def revision_items(
        self, revisions: Sequence[StepRevision]
    ) -> list[RevisionItemView]:
        """Build `RevisionItem`s."""
        people = await self.people(r.created_by for r in revisions)
        return [
            RevisionItemView(
                id=r.id,
                kind=r.kind.value,
                label=r.label,
                created_by=people[r.created_by],
                created_at=r.created_at,
                published=r.published_at is not None,
            )
            for r in revisions
        ]

    # - - - Pending and versions - - -

    def pending_changes(self, pending: Pending) -> PendingChangesView:
        """Build `PendingChanges`."""
        return PendingChangesView(
            draft_seq=pending.draft_seq,
            outline_changed=pending.outline_changed,
            steps=[
                PendingStepView(
                    step_id=s.step_id,
                    title=s.title,
                    change=s.change.value,
                    via_mcp=s.via_mcp,
                    via_ai=s.via_ai,
                )
                for s in pending.steps
            ],
        )

    async def version_items(
        self, versions: Sequence[CourseVersion]
    ) -> list[VersionItemView]:
        """Build `VersionItem`s."""
        people = await self.people(v.published_by for v in versions)
        return [version_item(v, people[v.published_by]) for v in versions]

    # - - - Staff - - -

    async def staff_items(
        self, members: Sequence[StaffMember]
    ) -> list[CourseStaffItemView]:
        """Build `CourseStaffItem`s ordered by position, then by name."""
        people = await self.people(m.user_id for m in members)
        items = [
            CourseStaffItemView(
                user=people[m.user_id],
                role=m.role,
                permissions=list(m.permissions),
                show_on_page=m.show_on_page,
                position=m.position,
            )
            for m in members
        ]
        return sorted(
            items, key=lambda i: (i.position, i.user.last_name, i.user.first_name)
        )


def version_item(version: CourseVersion, author: PersonRefView) -> VersionItemView:
    """Build `VersionItem`; `changes` is stored as lists of step IDs."""
    changes = version.changes
    return VersionItemView(
        number=version.number,
        published_by=author,
        published_at=version.created_at,
        note=version.note,
        changes=VersionChangesView(
            added=_count(changes.get("added")),
            changed=_count(changes.get("changed")),
            removed=_count(changes.get("removed")),
            outline_changed=bool(changes.get("outline_changed", False)),
        ),
    )


def _count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    return value if isinstance(value, int) else 0


def _step_status(step: CourseStep) -> Literal["new", "changed", "unchanged"]:
    if step.live_revision_id is None:
        return "new"
    return "changed" if step.draft_hash != step.live_hash else "unchanged"


def _badges(pending: Pending) -> dict[UUID, Badge]:
    badges: dict[UUID, Badge] = {}
    for item in pending.steps:
        if item.change is StepChange.REMOVED:
            continue
        if item.via_ai:
            badges[item.step_id] = "ai"
        elif item.via_mcp:
            badges[item.step_id] = "mcp"
        elif item.change is StepChange.ADDED:
            badges[item.step_id] = "new"
        else:
            badges[item.step_id] = "changed"
    return badges

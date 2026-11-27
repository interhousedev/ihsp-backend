"""Course badges: staff editing, awarding on progress, and the learner views.

Awards are replayed from stored facts, so they are granted both right after a
step changes state (``award_badges`` from ``refresh_progress``) and lazily when
a learner opens their badges (badges created after the fact still count).
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.step_context import load_course, staff_access
from app.modules.lms.domain.badges import (
    DESCRIPTION_MAX,
    MAX_BADGES_PER_COURSE,
    NAME_MAX,
    BadgeDesign,
    BadgeEvent,
    BadgeIcon,
    BadgeShape,
    check_image,
    clean_color,
    clean_texts,
    dump_rule,
    earned,
    parse_rule,
)
from app.modules.lms.domain.learning.access import EDIT, REVIEW
from app.modules.lms.domain.learning.entities import Enrollment
from app.modules.lms.domain.learning.live import LiveManifest
from app.modules.lms.ports.badge_repository import StoredAward, StoredBadge
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.base_error import ConflictError, NotFoundError
from app.shared.clock import Clock, to_local
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

from pydantic import BaseModel, Field


class BadgeNotFoundError(NotFoundError):
    """The badge does not exist in this course."""

    code = "lms/badge-not-found"
    message_key = "lms-badge-not-found"


class BadgeAwardNotFoundError(NotFoundError):
    """The award does not exist or belongs to someone else."""

    code = "lms/badge-award-not-found"
    message_key = "lms-badge-award-not-found"


class BadgeLimitError(ConflictError):
    """The course already has the maximum number of badges (`params.limit`)."""

    code = "lms/badge-limit"
    message_key = "lms-badge-limit"


# - - - views - - -


class LocalizedText(BaseModel):
    """A text in the three interface languages."""

    en: str = ""
    ru: str = ""
    uz: str = ""


class BadgeDesignView(BaseModel):
    """How a badge looks: a built-in icon in a frame, or an uploaded image."""

    icon: BadgeIcon
    shape: BadgeShape
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    image_url: str | None = None


class BadgeInput(BaseModel):
    """POST/PUT body of a badge; `rule` is validated as a bounded tree."""

    name: LocalizedText
    description: LocalizedText = LocalizedText()
    design: BadgeDesignView
    rule: dict[str, object]


class BadgeView(BaseModel):
    """A badge as course staff see it."""

    id: UUID
    course_id: UUID
    name: LocalizedText
    description: LocalizedText
    design: BadgeDesignView
    rule: dict[str, object]
    awarded_count: int
    created_at: datetime


class BadgeListView(BaseModel):
    """The badges of a course and whether learners see the locked ones."""

    show_locked: bool
    items: list[BadgeView]


class BadgeSettingsInput(BaseModel):
    """PUT body of the course badge settings."""

    show_locked: bool


class BadgePublicView(BaseModel):
    """A badge as learners see it (no rule)."""

    id: UUID
    name: LocalizedText
    description: LocalizedText
    design: BadgeDesignView


class EarnedBadgeView(BaseModel):
    """A badge the learner earned."""

    award_id: UUID
    badge: BadgePublicView
    course_id: UUID
    course_title: str
    awarded_at: datetime


class LockedBadgeView(BaseModel):
    """A badge not earned yet; `hint` is the rule event key for the client."""

    badge: BadgePublicView
    course_id: UUID
    course_title: str
    hint: BadgeEvent


class MyBadgesView(BaseModel):
    """The learner's earned and locked badges and the awards not celebrated yet."""

    earned: list[EarnedBadgeView]
    locked: list[LockedBadgeView]
    unseen: list[UUID]


class UserBadgesView(BaseModel):
    """The badges of a learner shown on their profile."""

    earned: list[EarnedBadgeView]


# - - - mapping - - -


def _image_url(file_id: UUID | None) -> str | None:
    return f"/files/{file_id}" if file_id else None


def _design_view(design: BadgeDesign) -> BadgeDesignView:
    return BadgeDesignView(
        icon=design.icon,
        shape=design.shape,
        color=design.color,
        image_url=_image_url(design.image_file_id),
    )


def _public(badge: StoredBadge) -> BadgePublicView:
    return BadgePublicView(
        id=badge.id,
        name=LocalizedText(**badge.design.name),
        description=LocalizedText(**badge.design.description),
        design=_design_view(badge.design),
    )


def _staff_view(badge: StoredBadge, awarded: int) -> BadgeView:
    return BadgeView(
        id=badge.id,
        course_id=badge.course_id,
        name=LocalizedText(**badge.design.name),
        description=LocalizedText(**badge.design.description),
        design=_design_view(badge.design),
        rule=dump_rule(badge.rule),
        awarded_count=awarded,
        created_at=badge.created_at,
    )


def _design(body: BadgeInput, image_file_id: UUID | None) -> BadgeDesign:
    """Validate the posted design; a null image_url removes the image."""
    return BadgeDesign(
        name=clean_texts("name", body.name.model_dump(), NAME_MAX, required=True),
        description=clean_texts(
            "description",
            body.description.model_dump(),
            DESCRIPTION_MAX,
            required=False,
        ),
        icon=body.design.icon,
        color=clean_color(body.design.color),
        shape=body.design.shape,
        image_file_id=image_file_id if body.design.image_url else None,
    )


def _earned_view(
    award: StoredAward, badge: StoredBadge, titles: Mapping[UUID, str]
) -> EarnedBadgeView:
    return EarnedBadgeView(
        award_id=award.id,
        badge=_public(badge),
        course_id=award.course_id,
        course_title=titles.get(award.course_id, "") if award.course_id else "",
        awarded_at=award.awarded_at,
    )


# - - - awarding - - -


async def award_badges(
    uow: LearningUnitOfWork,
    enrollment: Enrollment,
    manifest: LiveManifest,
    now: datetime,
) -> list[UUID]:
    """Grant the enabled badges whose rule the learner now meets; return new ones."""
    badges = [b for b in await uow.badges.for_course(enrollment.course_id) if b.enabled]
    if not badges:
        return []
    facts = await uow.badges.facts(
        enrollment.user_id,
        enrollment.course_id,
        [(s.id, [step.step_id for step in s.steps]) for s in manifest.sections],
        enrollment.completed_at,
        to_local(now).date(),
    )
    if facts is None:
        return []
    granted = []
    for badge_id in earned({b.id: b.rule for b in badges}, facts):
        if await uow.badges.award(
            badge_id, enrollment.user_id, enrollment.course_id, now
        ):
            granted.append(badge_id)
    return granted


# - - - service - - -


class BadgeService:
    """Every badge use case (`container.lms.badges`)."""

    def __init__(
        self,
        uow_factory: Callable[[], LearningUnitOfWork],
        files: FilesApi,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.clock = clock

    # - - - staff - - -

    async def _list(self, uow: LearningUnitOfWork, course_id: UUID) -> BadgeListView:
        badges = await uow.badges.for_course(course_id)
        counts = await uow.badges.award_counts(course_id)
        return BadgeListView(
            show_locked=await uow.badges.show_locked(course_id),
            items=[_staff_view(b, counts.get(b.id, 0)) for b in badges],
        )

    async def _badge(
        self, uow: LearningUnitOfWork, actor: Actor, course_id: UUID, badge_id: UUID
    ) -> StoredBadge:
        await load_course(uow, course_id)
        (await staff_access(uow, actor, course_id)).require(EDIT)
        badge = await uow.badges.get(badge_id)
        if badge is None or badge.course_id != course_id:
            raise BadgeNotFoundError(params={"badge_id": str(badge_id)})
        return badge

    async def _view(self, uow: LearningUnitOfWork, badge_id: UUID) -> BadgeView:
        badge = await uow.badges.get(badge_id)
        if badge is None:
            raise BadgeNotFoundError(params={"badge_id": str(badge_id)})
        counts = await uow.badges.award_counts(badge.course_id)
        return _staff_view(badge, counts.get(badge_id, 0))

    async def list_course(self, actor: Actor, course_id: UUID) -> BadgeListView:
        """Return the badges of a course; needs the `review` permission."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(REVIEW)
            return await self._list(uow, course_id)

    async def create(
        self, actor: Actor, course_id: UUID, body: BadgeInput
    ) -> BadgeView:
        """Create a badge; needs the `edit` permission."""
        design = _design(body, None)
        rule = parse_rule(body.rule)
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(EDIT)
            if await uow.badges.count(course_id) >= MAX_BADGES_PER_COURSE:
                raise BadgeLimitError(params={"limit": MAX_BADGES_PER_COURSE})
            badge_id = await uow.badges.add(
                course_id, design, rule, True, actor.user_id
            )
            await uow.commit()
            return await self._view(uow, badge_id)

    async def update(
        self, actor: Actor, course_id: UUID, badge_id: UUID, body: BadgeInput
    ) -> BadgeView:
        """Replace a badge's texts, design and rule; awards already given stay."""
        rule = parse_rule(body.rule)
        async with self.uow_factory() as uow:
            badge = await self._badge(uow, actor, course_id, badge_id)
            design = _design(body, badge.design.image_file_id)
            await uow.badges.update(badge_id, design, rule, badge.enabled)
            await uow.commit()
            return await self._view(uow, badge_id)

    async def delete(self, actor: Actor, course_id: UUID, badge_id: UUID) -> None:
        """Remove a badge and its awards."""
        async with self.uow_factory() as uow:
            await self._badge(uow, actor, course_id, badge_id)
            await uow.badges.delete(badge_id)
            await uow.commit()

    async def upload_image(
        self,
        actor: Actor,
        course_id: UUID,
        badge_id: UUID,
        *,
        name: str,
        content_type: str,
        data: bytes,
    ) -> BadgeView:
        """Store a small PNG/JPEG/WebP as the badge image."""
        check_image(content_type, len(data))
        async with self.uow_factory() as uow:
            await self._badge(uow, actor, course_id, badge_id)
        stored = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.COURSE,
            purpose=FilePurpose.LINK,
            name=name[:200] or "badge",
            data=data,
        )
        async with self.uow_factory() as uow:
            badge = await self._badge(uow, actor, course_id, badge_id)
            old = badge.design
            design = BadgeDesign(
                old.name, old.description, old.icon, old.color, old.shape, stored.id
            )
            await uow.badges.update(badge_id, design, badge.rule, badge.enabled)
            await uow.commit()
            return await self._view(uow, badge_id)

    async def set_settings(
        self, actor: Actor, course_id: UUID, body: BadgeSettingsInput
    ) -> BadgeListView:
        """Choose whether learners see badges they have not earned yet."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(EDIT)
            await uow.badges.set_show_locked(course_id, body.show_locked)
            await uow.commit()
            return await self._list(uow, course_id)

    # - - - learner - - -

    async def mine(self, actor: Actor) -> MyBadgesView:
        """Award what is due, then return earned, locked and unseen badges."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            enrollments = await uow.enrollments.list_for_user(actor.user_id)
            course_ids = [e.course_id for e in enrollments]
            courses = {c.id: c for c in await uow.courses.get_many(course_ids)}
            badges = await uow.badges.for_courses(course_ids)
            with_badges = {b.course_id for b in badges}
            for enrollment in enrollments:
                course = courses.get(enrollment.course_id)
                if course is None or course.id not in with_badges:
                    continue
                if course.live_version_id is None:
                    continue
                version = await uow.versions.get(course.live_version_id)
                if version is not None:
                    await award_badges(uow, enrollment, version.manifest, now)
            await uow.commit()
            awards = await uow.badges.awards_of(actor.user_id)
            show = {cid: await uow.badges.show_locked(cid) for cid in with_badges}
        titles = {cid: c.title for cid, c in courses.items()}
        by_id = {b.id: b for b in badges}
        mine = [a for a in awards if a.badge_id in by_id]
        got = {a.badge_id for a in mine}
        return MyBadgesView(
            earned=[_earned_view(a, by_id[a.badge_id], titles) for a in mine],
            locked=[
                LockedBadgeView(
                    badge=_public(b),
                    course_id=b.course_id,
                    course_title=titles.get(b.course_id, ""),
                    hint=b.rule.event,
                )
                for b in badges
                if b.enabled and b.id not in got and show.get(b.course_id, True)
            ],
            unseen=[a.id for a in mine if a.seen_at is None],
        )

    async def mark_seen(self, actor: Actor, award_id: UUID) -> None:
        """Record that the learner saw the celebration of an award."""
        async with self.uow_factory() as uow:
            award = await uow.badges.get_award(award_id)
            if award is None or award.user_id != actor.user_id:
                raise BadgeAwardNotFoundError(params={"award_id": str(award_id)})
            await uow.badges.mark_seen(award_id, self.clock.now())
            await uow.commit()

    async def of_user(self, actor: Actor, user_id: UUID) -> UserBadgesView:
        """Return a learner's earned badges in courses the actor shares with them.

        The learner and LMS administrators see all; course staff and classmates see
        the awards of the courses they teach or take.
        """
        async with self.uow_factory() as uow:
            awards = await uow.badges.awards_of(user_id)
            course_ids = list({a.course_id for a in awards if a.course_id})
            if actor.user_id != user_id and not actor.has(Role.LMS_ADMIN):
                shared = {
                    e.course_id
                    for e in await uow.enrollments.list_for_user(actor.user_id)
                }
                for course_id in course_ids:
                    if await uow.staff.get(course_id, actor.user_id) is not None:
                        shared.add(course_id)
                course_ids = [c for c in course_ids if c in shared]
            badges = {b.id: b for b in await uow.badges.for_courses(course_ids)}
            titles = {c.id: c.title for c in await uow.courses.get_many(course_ids)}
        return UserBadgesView(
            earned=[
                _earned_view(a, badges[a.badge_id], titles)
                for a in awards
                if a.badge_id in badges
            ]
        )

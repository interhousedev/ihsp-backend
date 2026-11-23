"""Enforcing the audience rules of courses and lessons on every learner read path."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.lms.application.learning.views import LearningContactView
from app.modules.lms.domain.access_rules import (
    GUEST,
    PUBLIC_RULE,
    AccessRule,
    AccessState,
    Audience,
    Viewer,
    combine,
    decide,
)
from app.modules.lms.domain.learning.errors import (
    ContentLockedError,
    CourseNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory

# Returns the group of an active student, or None.
StudentGroupLookup = Callable[[UUID], Awaitable[UUID | None]]
# Raises when a step is locked for the viewer (actor, course_id, step_id).
StepLock = Callable[[Actor | None, UUID, UUID], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CourseAccess:
    """The state of a course and of its restricted steps for one viewer."""

    state: AccessState
    audience: Audience
    steps: dict[UUID, AccessState] = field(default_factory=dict)
    step_audiences: dict[UUID, Audience] = field(default_factory=dict)
    needs_contact: bool = False

    def step(self, step_id: UUID) -> AccessState:
        """Give the effective state of a step, the course state included."""
        return combine(self.state, self.steps.get(step_id, AccessState.OPEN))

    def visible(self, step_ids: Sequence[UUID]) -> list[UUID]:
        """Return the steps the viewer sees in the outline (open or locked)."""
        return [s for s in step_ids if self.step(s) is not AccessState.HIDDEN]

    def readable(self, step_ids: Sequence[UUID]) -> list[UUID]:
        """Return the steps the viewer may open, so may complete."""
        return [s for s in step_ids if self.step(s) is AccessState.OPEN]


class AudienceGate:
    """Decides what a viewer may see; staff and LMS administrators pass."""

    def __init__(
        self,
        identity: IdentityDirectory,
        student_group: StudentGroupLookup | None = None,
    ) -> None:
        """Store collaborators; without a lookup, group rules match nobody."""
        self.identity = identity
        self.student_group = student_group
        # Mastery unlock check (engagement); set by the wiring.
        self.step_lock: StepLock | None = None

    async def actor_for(self, user_id: UUID) -> Actor:
        """Return an actor with the user's current roles (for user-id callers)."""
        users = await self.identity.get_users([user_id])
        user = users.get(user_id)
        roles = user.roles if user is not None else frozenset()
        return Actor(user_id=user_id, roles=roles)

    async def viewer(
        self, uow: LearningUnitOfWork, actor: Actor | None, course_id: UUID | None
    ) -> Viewer:
        """Return the viewer; `course_id=None` checks only the LMS admin bypass."""
        if actor is None:
            return GUEST
        bypass = actor.has(Role.LMS_ADMIN)
        if not bypass and course_id is not None:
            bypass = await uow.staff.get(course_id, actor.user_id) is not None
        is_student = actor.has(Role.STUDENT)
        group_id = (
            await self.student_group(actor.user_id)
            if is_student and self.student_group is not None
            else None
        )
        return Viewer(
            user_id=actor.user_id,
            is_student=is_student,
            group_id=group_id,
            bypass=bypass,
        )

    async def course(
        self, uow: LearningUnitOfWork, actor: Actor | None, course_id: UUID
    ) -> CourseAccess:
        """Return the state of the course and its steps for the actor."""
        rules = await uow.access.for_course(course_id)
        viewer = await self.viewer(uow, actor, course_id)
        return _access(course_id, rules, viewer)

    async def courses(
        self, uow: LearningUnitOfWork, actor: Actor | None, course_ids: Sequence[UUID]
    ) -> dict[UUID, CourseAccess]:
        """Return the access of each course and its steps (for lists)."""
        rules = await uow.access.for_courses(course_ids)
        staff_of: set[UUID] = set()
        if actor is not None and rules and not actor.has(Role.LMS_ADMIN):
            staff_of = set(await uow.staff.course_ids_of(actor.user_id))
        base = await self.viewer(uow, actor, None)
        result: dict[UUID, CourseAccess] = {}
        for course_id in course_ids:
            viewer = base
            if course_id in staff_of:
                viewer = Viewer(user_id=base.user_id, bypass=True)
            result[course_id] = _access(course_id, rules.get(course_id, {}), viewer)
        return result

    async def require_course(
        self, uow: LearningUnitOfWork, actor: Actor | None, course_id: UUID
    ) -> CourseAccess:
        """Raise unless the actor may open the course; return its access."""
        access = await self.course(uow, actor, course_id)
        _raise(access.state, CourseNotFoundError(params={"course_id": str(course_id)}))
        return access

    async def require_visible(
        self, uow: LearningUnitOfWork, actor: Actor | None, course_id: UUID
    ) -> CourseAccess:
        """Raise when the course is hidden from the actor; locked courses pass."""
        access = await self.course(uow, actor, course_id)
        if access.state is AccessState.HIDDEN:
            raise CourseNotFoundError(params={"course_id": str(course_id)})
        return access

    async def require_step(
        self,
        uow: LearningUnitOfWork,
        actor: Actor | None,
        course_id: UUID,
        step_id: UUID,
    ) -> None:
        """Raise unless the actor may open the step and its course."""
        access = await self.course(uow, actor, course_id)
        _raise(
            access.step(step_id), StepNotFoundError(params={"step_id": str(step_id)})
        )
        if self.step_lock is not None:
            await self.step_lock(actor, course_id, step_id)

    async def contact(
        self, uow: LearningUnitOfWork, course_id: UUID, *, signed_in: bool
    ) -> LearningContactView | None:
        """Return the course lead's name; the Telegram username only when signed in."""
        lead = await uow.access.lead(course_id)
        if lead is None:
            return None
        user = (await self.identity.get_users([lead])).get(lead)
        if user is None:
            return None
        username = None
        if signed_in:
            accounts = await self.identity.telegram_accounts(lead)
            username = next(
                (a.username for a in accounts if a.username and not a.blocked), None
            )
        return LearningContactView(
            name=f"{user.first_name} {user.last_name}".strip(), telegram=username
        )


def _access(
    course_id: UUID, rules: dict[UUID, AccessRule], viewer: Viewer
) -> CourseAccess:
    """Decide the course and its step rules for one viewer."""
    course_rule = rules.get(course_id, PUBLIC_RULE)
    steps: dict[UUID, AccessState] = {}
    audiences: dict[UUID, Audience] = {}
    needs_contact = _contact(course_rule, viewer)
    for target, rule in rules.items():
        if target == course_id:
            continue
        audiences[target] = rule.audience
        state = decide(rule, viewer)
        if state is not AccessState.OPEN:
            steps[target] = state
            needs_contact = needs_contact or _contact(rule, viewer)
    return CourseAccess(
        state=decide(course_rule, viewer),
        audience=course_rule.audience,
        steps=steps,
        step_audiences=audiences,
        needs_contact=needs_contact,
    )


def _contact(rule: AccessRule, viewer: Viewer) -> bool:
    """Return True when a locked chosen-audience item shows whom to ask."""
    return rule.audience is Audience.CHOSEN and (
        decide(rule, viewer) is AccessState.LOCKED
    )


def _raise(state: AccessState, missing: Exception) -> None:
    """Raise the not-found error for hidden items and a 403 for locked ones."""
    if state is AccessState.HIDDEN:
        raise missing
    if state is AccessState.LOCKED:
        raise ContentLockedError()

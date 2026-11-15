"""Use cases: read and set who may open a course or one of its lessons."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.access_rules import (
    MAX_CHOSEN,
    PUBLIC_RULE,
    AccessRule,
    Audience,
    WhenDenied,
)
from app.modules.lms.domain.authoring.course_settings import bad
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.authoring.permissions import MANAGE_STAFF
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor
from app.shared.contracts.academic import GroupDirectory
from app.shared.contracts.identity import IdentityDirectory
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import BaseModel


class AccessUserView(BaseModel):
    """A chosen person, with a name for the editor."""

    id: UUID
    name: str


class AccessRuleView(BaseModel):
    """`AccessRule`: the audience of a course or a lesson."""

    audience: Audience
    when_denied: WhenDenied
    group_ids: list[UUID]
    users: list[AccessUserView]


class StepAccessRuleView(BaseModel):
    """The rule of one lesson that is not public."""

    step_id: UUID
    rule: AccessRuleView


class CourseAccessRulesView(BaseModel):
    """`CourseAccessRules`: the course rule and every restricted lesson."""

    course: AccessRuleView
    steps: list[StepAccessRuleView]


async def _views(
    identity: IdentityDirectory, rules: list[AccessRule]
) -> list[AccessRuleView]:
    ids = list(dict.fromkeys(u for rule in rules for u in rule.user_ids))
    users = await identity.get_users(ids) if ids else {}

    def name(user_id: UUID) -> str:
        user = users.get(user_id)
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip()

    return [
        AccessRuleView(
            audience=rule.audience,
            when_denied=rule.when_denied,
            group_ids=list(rule.group_ids),
            users=[AccessUserView(id=u, name=name(u)) for u in rule.user_ids],
        )
        for rule in rules
    ]


async def _rules_view(
    uow: AuthoringUnitOfWork, identity: IdentityDirectory, course_id: UUID
) -> CourseAccessRulesView:
    rules = await uow.access.for_course(course_id)
    step_ids = [target for target in rules if target != course_id]
    views = await _views(
        identity,
        [rules.get(course_id, PUBLIC_RULE), *(rules[s] for s in step_ids)],
    )
    return CourseAccessRulesView(
        course=views[0],
        steps=[
            StepAccessRuleView(step_id=s, rule=v)
            for s, v in zip(step_ids, views[1:], strict=True)
        ],
    )


class GetAccessRules:
    """Return the audience rules of a course for its staff."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, actor: Actor, course_id: UUID) -> CourseAccessRulesView:
        """Raise unless the actor is course staff or an LMS admin."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require_staff()
            access.require_read_scope()
            return await _rules_view(uow, self.identity, course_id)


class SetAccessRule:
    """Change the audience of a course or a lesson (owner or LMS admin only)."""

    def __init__(
        self,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        groups: GroupDirectory | None = None,
    ) -> None:
        """Store collaborators; ``groups`` validates the chosen group ids."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.groups = groups

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        rule: AccessRule,
        *,
        step_id: UUID | None = None,
    ) -> CourseAccessRulesView:
        """Validate and store the rule; the step rule applies within the course."""
        rule = await self._clean(rule)
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            access.require_scope(COURSES_WRITE)
            if step_id is not None:
                step = await uow.steps.get(step_id)
                if step is None or step.course_id != course_id:
                    raise StepNotFoundError(params={"step_id": str(step_id)})
            target = step_id if step_id is not None else course_id
            await uow.access.save(course_id, target, rule, actor.user_id)
            await uow.commit()
            return await _rules_view(uow, self.identity, course_id)

    async def _clean(self, rule: AccessRule) -> AccessRule:
        """Drop duplicates, check the chosen lists and the people and groups."""
        if rule.audience is not Audience.CHOSEN:
            return AccessRule(rule.audience, rule.when_denied)
        groups = tuple(dict.fromkeys(rule.group_ids))
        users = tuple(dict.fromkeys(rule.user_ids))
        if not groups and not users:
            raise bad("audience", "chosen-empty")
        if len(groups) + len(users) > MAX_CHOSEN:
            raise bad("audience", "too-many")
        if groups and self.groups is not None:
            if set(groups) - await self.groups.existing_group_ids(list(groups)):
                raise bad("group_ids", "unknown-group")
        if users and set(users) - set(await self.identity.get_users(list(users))):
            raise bad("user_ids", "unknown-user")
        return AccessRule(rule.audience, rule.when_denied, groups, users)

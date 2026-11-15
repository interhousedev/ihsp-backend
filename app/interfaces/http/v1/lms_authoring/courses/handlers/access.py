"""Audience routes: who may open a course or one of its lessons."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.modules.lms.application.authoring.access_rules import CourseAccessRulesView
from app.modules.lms.domain.access_rules import (
    MAX_CHOSEN,
    AccessRule,
    Audience,
    WhenDenied,
)

from pydantic import BaseModel, Field


class AccessRuleBody(BaseModel):
    """The audience; the lists count only for `chosen`."""

    audience: Audience
    when_denied: WhenDenied = WhenDenied.HIDDEN
    group_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CHOSEN)
    user_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CHOSEN)

    def rule(self) -> AccessRule:
        """Return the domain rule."""
        return AccessRule(
            self.audience,
            self.when_denied,
            tuple(self.group_ids),
            tuple(self.user_ids),
        )


async def get_access(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> CourseAccessRulesView:
    """Return the course rule and the rules of restricted lessons (course staff)."""
    return await authoring.get_access_rules.execute(actor, course_id)


async def set_course_access(
    course_id: UUID, body: AccessRuleBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseAccessRulesView:
    """Set the course audience; the owner or an LMS admin only."""
    return await authoring.set_access_rule.execute(actor, course_id, body.rule())


async def set_step_access(
    course_id: UUID,
    step_id: UUID,
    body: AccessRuleBody,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> CourseAccessRulesView:
    """Set a lesson audience; it applies only inside an accessible course."""
    return await authoring.set_access_rule.execute(
        actor, course_id, body.rule(), step_id=step_id
    )

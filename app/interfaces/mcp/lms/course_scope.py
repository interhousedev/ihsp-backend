"""Course restriction of LMS connectors (MCP-2, MCP-5).

A connector may be limited to some courses (`course_ids`). The restriction comes
from `course:<uuid>` scopes on the actor, or from the optional ConnectorCoursesPort.
The user's `edit` permission on the course is checked by the LMS use cases.
"""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.errors import McpCourseNotAllowedError
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.actor import Actor

COURSE_SCOPE_PREFIX = "course:"


def _from_scopes(scopes: frozenset[str]) -> frozenset[UUID] | None:
    """Return the courses named by `course:<uuid>` scopes; None if there are none.

    A malformed marker still counts as a restriction (it just allows nothing).
    """
    markers = [s for s in scopes if s.startswith(COURSE_SCOPE_PREFIX)]
    if not markers:
        return None
    ids: set[UUID] = set()
    for marker in markers:
        try:
            ids.add(UUID(marker.removeprefix(COURSE_SCOPE_PREFIX)))
        except ValueError:
            continue
    return frozenset(ids)


async def allowed_courses(kit: ToolKit, actor: Actor) -> frozenset[UUID] | None:
    """Return the courses the caller is limited to; None means no limit."""
    marked = _from_scopes(actor.scopes)
    if marked is not None:
        return marked
    port = kit.deps.connector_courses
    if actor.connector_id is not None and port is not None:
        return await port.allowed_course_ids(actor.connector_id)
    return None


def ensure_allowed(allowed: frozenset[UUID] | None, course_id: UUID | None) -> None:
    """Raise unless the course is inside the restriction."""
    if allowed is None:
        return
    if course_id is None or course_id not in allowed:
        raise McpCourseNotAllowedError()


async def ensure_course(kit: ToolKit, actor: Actor, course_id: UUID) -> None:
    """Refuse a course outside the connector's restriction."""
    ensure_allowed(await allowed_courses(kit, actor), course_id)


def course_id_of(draft: dict[str, Any]) -> UUID | None:
    """Read `course_id` of a step draft; None if absent or malformed."""
    try:
        return UUID(str(draft.get("course_id")))
    except ValueError:
        return None


async def ensure_step(kit: ToolKit, actor: Actor, step_id: UUID) -> None:
    """Refuse a step whose course is outside the restriction.

    Costs one read, and only when the connector is limited to some courses.
    """
    allowed = await allowed_courses(kit, actor)
    if allowed is None:
        return
    draft = await kit.deps.lms_queries.step_draft(step_id, actor)
    ensure_allowed(allowed, course_id_of(draft))

"""Shared pieces of the applicant tools: the caller's context and parameter types."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import NotApplicantError

from pydantic import Field

Locale = Annotated[
    Literal["uz", "ru", "en"],
    Field(description="Language of the generated text: uz, ru or en."),
]
ItemId = Annotated[UUID, Field(description="Id of one of the student's activities.")]
LockVersion = Annotated[
    int,
    Field(description="`lock_version` from the last read; a stale one is refused."),
]


def services(kit: ToolKit) -> Any:  # AdmissionServices; deps keep it untyped
    """The admission services; call it inside a tool body, never at register time.

    `deps.admission` is unset when the server is built without the admission module
    (tests, processes without admission), so it is resolved per call.
    """
    adm = kit.deps.admission
    if adm is None:
        raise RuntimeError("the admission module is not wired into the MCP server")
    return adm


class _LazyServices:
    """Resolves every attribute through `services` at the moment it is used."""

    def __init__(self, kit: ToolKit) -> None:
        self._kit = kit

    def __getattr__(self, name: str) -> Any:  # one of the AdmissionServices fields
        return getattr(services(self._kit), name)


def lazy_services(kit: ToolKit) -> Any:  # proxies AdmissionServices
    """A register-time alias of `services(kit)` that still resolves per call."""
    return _LazyServices(kit)


async def applicant(kit: ToolKit) -> AdmissionContext:
    """The admission context of the calling student; others are refused."""
    ctx: AdmissionContext = await services(kit).actor.execute(current_actor())
    if not ctx.admission.is_applicant:
        raise NotApplicantError()
    return ctx


def require_fields(changes: dict[str, object]) -> dict[str, object]:
    """A patch must change something."""
    if not changes:
        raise McpInvalidInputError(params={"reason": "no field to change"})
    return changes

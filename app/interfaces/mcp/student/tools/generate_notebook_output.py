"""Students tool `generate_notebook_output`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "notebooks:write"
OutputKind = Literal[
    "report",
    "mind_map",
    "flashcards",
    "quiz",
    "data_table",
    "slides",
    "infographic",
    "exercise",
]


def register(kit: ToolKit) -> None:
    """Register `generate_notebook_output`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("notebook_id", "kind")))
    async def generate_notebook_output(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
        kind: OutputKind,
        options: Annotated[
            dict[str, Any] | None,
            Field(description='Options of the kind, e.g. quiz: {"count": 10}.'),
        ] = None,
        focus: Annotated[
            str | None, Field(max_length=1000, description="What to focus on.")
        ] = None,
    ) -> dict[str, Any]:
        """Ask the Studio to generate an output; this spends the student's AI budget.

        It runs in the background: check `list_notebook_outputs` for its status.
        """
        actor = current_actor()
        found = await kit.deps.content_tools.generate_notebook_output(
            actor, notebook_id, kind=kind, options=options or {}, focus=focus
        )
        return {**found, "links": kit.deps.web_links.notebook(notebook_id)}

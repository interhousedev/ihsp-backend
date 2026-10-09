"""Collaborators that cannot exist yet when the module is built.

The links module needs `AiQueries` to build and the assistant needs `LinksApi`
for lesson materials, so integration (I1) binds them after both are built. The
notebooks and LMS modules are built after the assistants, so the notebook tools
and the course author assistant reach them through these bindings too.
"""

from dataclasses import dataclass

from app.modules.ai.ports.share_lookup import ChatShareLookup
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import (
    LmsDraftCommands,
    LmsQueries,
    LmsWorkspace,
    LmsWorkspaceCommands,
)
from app.shared.contracts.notebooks import NotebooksCommands, NotebooksQueries


@dataclass(slots=True)
class LateBindings:
    """Optional collaborators set after construction (None until bound)."""

    links: LinksApi | None = None
    share_lookup: ChatShareLookup | None = None
    notebooks: NotebooksQueries | None = None
    notebooks_commands: NotebooksCommands | None = None
    # The course author assistant (lms_author); all four are needed for it.
    lms_workspace: LmsWorkspace | None = None
    lms_workspace_commands: LmsWorkspaceCommands | None = None
    lms_queries: LmsQueries | None = None
    lms_draft_commands: LmsDraftCommands | None = None

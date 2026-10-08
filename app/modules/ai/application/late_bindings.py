"""Collaborators that cannot exist yet when the module is built.

The links module needs `AiQueries` to build and the assistant needs `LinksApi`
for lesson materials, so integration (I1) binds them after both are built.
"""

from dataclasses import dataclass

from app.modules.ai.ports.share_lookup import ChatShareLookup
from app.shared.contracts.links import LinksApi


@dataclass(slots=True)
class LateBindings:
    """Optional collaborators set after construction (None until bound)."""

    links: LinksApi | None = None
    share_lookup: ChatShareLookup | None = None

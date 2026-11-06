"""A file a notebook is grounded in, for the MCP file catalog."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NotebookFile:
    """`origin` is the notebook's origin; `shared` when someone shared it with me."""

    file_id: UUID
    notebook_id: UUID
    origin: str
    shared: bool

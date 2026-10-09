"""Port: storage of topic labels, their links to sources and the auto run state."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.labels import (
    LabelLink,
    LabelOrigin,
    LabelRun,
    SourceLabel,
)


class LabelRepository(Protocol):
    """Rows of `source_labels`, `source_label_links` and `source_label_runs`."""

    async def list_for_notebook(self, notebook_id: UUID) -> list[SourceLabel]:
        """The labels of a notebook by `position`, with their `source_count`."""
        ...

    async def get(self, label_id: UUID) -> SourceLabel | None:
        """The label with its `source_count`."""
        ...

    async def add(self, label: SourceLabel) -> None:
        """Insert a label."""
        ...

    async def save(self, label: SourceLabel) -> None:
        """Write the name, emoji, position and origin of a label."""
        ...

    async def delete(self, label_ids: Sequence[UUID]) -> None:
        """Delete labels (their links cascade)."""
        ...

    async def links_for_notebook(self, notebook_id: UUID) -> list[LabelLink]:
        """Every link of the notebook's sources."""
        ...

    async def replace_links(
        self, source_id: UUID, label_ids: Sequence[UUID], origin: LabelOrigin
    ) -> None:
        """Make exactly these labels the source's links, all with `origin`."""
        ...

    async def add_links(self, links: Sequence[LabelLink]) -> None:
        """Insert links (a link that exists is left as it is)."""
        ...

    async def delete_links(
        self, source_ids: Sequence[UUID], origin: LabelOrigin
    ) -> None:
        """Delete the links of `origin` that these sources have."""
        ...

    async def get_run(self, notebook_id: UUID) -> LabelRun | None:
        """The auto run state, None when the notebook never ran one."""
        ...

    async def save_run(self, run: LabelRun) -> None:
        """Insert or update the auto run state."""
        ...

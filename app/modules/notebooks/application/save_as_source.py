"""Use case: add a report to the notebook as a `note` source (§ 3.4.1, § 3.4.10)."""

import re
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import (
    PROCESS_SOURCE_TASK,
    require_ready,
)
from app.modules.notebooks.application.note_sources import create_note_source
from app.modules.notebooks.domain.artifacts.report_markdown import (
    strip_citation_marks,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

_SPACE_BEFORE_MARK = re.compile(r"[ \t]+(?=⟦)")


def plain_markdown(markdown: str) -> str:
    """The report text without the `⟦n⟧` chips and the space in front of them."""
    return strip_citation_marks(_SPACE_BEFORE_MARK.sub("", markdown))


class SaveAsSource:
    """Turns a ready report into a note source without citations."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        kicker: TaskKicker,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.kicker = kicker
        self.clock = clock
        self.settings = settings

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> Source:
        """Create the note (titled like the report) and start its processing.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The output is not a report.
            ArtifactNotReadyError: The report is not ready.
            SourceLimitError: The notebook is full.
        """
        user_id = actor.user_id
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, user_id, notebook_id, for_update=True)
            artifact = await load_artifact(uow, user_id, notebook_id, artifact_id)
            content = require_ready(artifact, ArtifactKind.REPORT)
            source = await create_note_source(
                uow,
                notebook,
                owner_id=notebook.owner_id,
                title=artifact.title,
                body_md=plain_markdown(str(content.get("markdown", ""))),
                citations=None,
                now=self.clock.now(),
                settings=self.settings,
            )
            uow.after_commit(
                partial(self.kicker.kick, PROCESS_SOURCE_TASK, source_id=str(source.id))
            )
            await uow.commit()
        return source

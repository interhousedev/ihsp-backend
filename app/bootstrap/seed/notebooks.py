"""Demo content of the notebooks: three text sources, a question and every output."""

from typing import Any
from uuid import UUID

from app.bootstrap.container import Container
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.source_input import SourceInput, TextInput
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError

import structlog

log = structlog.get_logger(__name__)

NOTEBOOK_TITLE = "Photosynthesis (demo)"
NOTEBOOK_EMOJI = "🌱"
QUESTION = "What does photosynthesis produce?"

TEXTS: tuple[tuple[str, str], ...] = (
    (
        "Photosynthesis in brief",
        "Photosynthesis is the process by which plants, algae and some bacteria "
        "turn light energy into chemical energy. It takes place in the "
        "chloroplasts, which contain the green pigment chlorophyll. The overall "
        "result is glucose and oxygen, made from carbon dioxide and water.",
    ),
    (
        "Light reactions",
        "The light reactions happen in the thylakoid membranes. Chlorophyll "
        "absorbs light and splits water, which releases oxygen. The energy is "
        "stored in two carriers, ATP and NADPH, that the next stage uses.",
    ),
    (
        "Calvin cycle",
        "The Calvin cycle runs in the stroma of the chloroplast. It uses ATP and "
        "NADPH to fix carbon dioxide into sugar. The enzyme Rubisco catches the "
        "carbon dioxide; the cycle does not need light directly but depends on "
        "the products of the light reactions.",
    ),
)

# One output of every kind this build can generate, with the options it needs.
OUTPUTS: tuple[tuple[ArtifactKind, dict[str, Any]], ...] = (
    (ArtifactKind.REPORT, {"format": "conspect"}),
    (ArtifactKind.MIND_MAP, {}),
    (ArtifactKind.FLASHCARDS, {}),
    (ArtifactKind.QUIZ, {}),
    (ArtifactKind.DATA_TABLE, {}),
    (ArtifactKind.SLIDES, {}),
    (ArtifactKind.INFOGRAPHIC, {}),
)


async def seed_notebook(container: Container, student_id: UUID) -> UUID | None:
    """Create the demo notebook of a student; None when it exists or no fake model.

    Runs the background jobs inline, so the data is complete without a worker. Only
    the fake model is used: seeding never spends tokens of a real provider.
    """
    if container.settings.openrouter.mode != "fake":
        return None
    notebooks = container.notebooks
    actor = Actor(user_id=student_id, roles=frozenset({Role.STUDENT}))
    existing = await notebooks.list_notebooks.execute(actor, q=NOTEBOOK_TITLE)
    if any(book.title == NOTEBOOK_TITLE for book in existing.items):
        return None
    notebook = await notebooks.create_notebook.execute(
        actor, NOTEBOOK_TITLE, NOTEBOOK_EMOJI
    )
    items: list[SourceInput] = [
        TextInput(title=title, text=text) for title, text in TEXTS
    ]
    added = await notebooks.add_sources.execute(actor, notebook.id, items)
    for source in added.items:
        await notebooks.process_source.execute(source.id)
        await notebooks.build_source_guide.execute(source.id)
    await notebooks.ask_notebook.execute(actor, notebook.id, QUESTION)
    for kind, options in OUTPUTS:
        try:
            artifact = await notebooks.request_artifact.execute(
                actor, notebook.id, kind, options, None
            )
            await notebooks.generate_artifact.execute(artifact.id)
        except BaseError as error:
            log.warning("seed_notebook_output_failed", kind=kind.value, type=error.code)
    log.info("seed_notebook_created", notebook_id=str(notebook.id))
    return notebook.id

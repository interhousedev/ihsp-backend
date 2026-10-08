"""Loading revisions and their student render, with the in-process cache."""

from uuid import UUID

from app.modules.lms.domain.learning.entities import RevisionData
from app.modules.lms.domain.learning.errors import BlockNotFoundError, StepNotFoundError
from app.modules.lms.domain.learning.live import (
    RenderCache,
    RenderedRevision,
    render_revision,
)
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    StepContent,
    TestBlock,
)
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


async def load_revision(uow: LearningUnitOfWork, revision_id: UUID) -> RevisionData:
    """Return the revision or raise StepNotFoundError."""
    revision = await uow.revisions.get(revision_id)
    if revision is None:
        raise StepNotFoundError(params={"revision_id": str(revision_id)})
    return revision


async def load_rendered(
    uow: LearningUnitOfWork, cache: RenderCache, revision_id: UUID
) -> RenderedRevision:
    """Return the student render of a revision, rendering it once per process."""
    cached = cache.get(revision_id)
    if cached is not None:
        return cached
    revision = await load_revision(uow, revision_id)
    rendered = render_revision(revision.id, revision.content)
    cache.put(rendered)
    return rendered


def find_test_block(content: StepContent, block_id: str) -> TestBlock:
    """Return the test block with this id or raise BlockNotFoundError."""
    for block in content.blocks:
        if isinstance(block, TestBlock) and block.id == block_id:
            return block
    raise BlockNotFoundError(params={"block_id": block_id})


def find_flashcards_block(content: StepContent, block_id: str) -> FlashcardsBlock:
    """Return the flash card block with this id or raise BlockNotFoundError."""
    for block in content.blocks:
        if isinstance(block, FlashcardsBlock) and block.id == block_id:
            return block
    raise BlockNotFoundError(params={"block_id": block_id})


def find_card_block(content: StepContent, card_id: str) -> FlashcardsBlock | None:
    """Return the flash card block that holds the card, if any."""
    for block in content.blocks:
        if isinstance(block, FlashcardsBlock) and any(
            card.id == card_id for card in block.cards
        ):
            return block
    return None

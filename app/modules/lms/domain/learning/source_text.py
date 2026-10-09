"""Step content as plain text for notebook sources (LMS-17: never the tests)."""

from app.modules.lms.domain.step_content import FlashcardsBlock, StepContent, TextBlock

BLOCK_SEPARATOR = "\n\n"


def export_text(content: StepContent) -> tuple[str, tuple[int, ...]]:
    """Return the readable text of a step and where each exported block starts.

    Text blocks give their Markdown, flash card blocks give ``Q: front`` and
    ``A: back`` for every card (cards separated by a blank line). Only these two
    kinds are exported: test blocks, with their questions, options, correct answers
    and explanations, never are. Blocks without text are skipped, so a step with
    only tests gives ``("", ())``.

    Returns:
        The blocks joined by a blank line, and the character offset of every
        exported block in that text.
    """
    pieces = [piece for block in content.blocks if (piece := _piece(block))]
    starts: list[int] = []
    offset = 0
    for piece in pieces:
        starts.append(offset)
        offset += len(piece) + len(BLOCK_SEPARATOR)
    return BLOCK_SEPARATOR.join(pieces), tuple(starts)


def _piece(block: object) -> str:
    """Return the text of one block, or '' for blocks that are not exported."""
    if isinstance(block, TextBlock):
        return block.markdown.strip()
    if isinstance(block, FlashcardsBlock):
        return BLOCK_SEPARATOR.join(
            f"Q: {card.front.strip()}\nA: {card.back.strip()}" for card in block.cards
        )
    return ""

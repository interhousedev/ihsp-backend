"""Whether an answer has renderable OpenUI blocks; the answer without bad ones."""

from app.shared.openui.blocks import split_blocks
from app.shared.openui.validate import validate_block


def has_valid_blocks(text: str) -> bool:
    """True when at least one closed block passes the validator."""
    return any(
        part.kind == "block" and not validate_block(part.text)
        for part in split_blocks(text)
    )


def keep_valid_blocks(text: str) -> str:
    """The answer with invalid or unfinished blocks removed (the text stays)."""
    out: list[str] = []
    for part in split_blocks(text):
        if part.kind == "text":
            out.append(part.text)
        elif part.kind == "block" and not validate_block(part.text):
            out.append(part.raw)
    return "".join(out)

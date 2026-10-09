"""Use case: export the actor's annotations as Markdown (LIB-8)."""

from uuid import UUID

from app.modules.library.domain.reader_annotation import Annotation
from app.modules.library.domain.reader_locator import locator_page
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

INDENT = "  "


def _position(annotation: Annotation) -> tuple[int, float]:
    """Sort key inside an item: pages first, then EPUB positions."""
    page = locator_page(annotation.locator)
    if page is not None:
        return (0, float(page))
    return (1, float(annotation.locator.get("progress", 0)))


def _where(annotation: Annotation) -> str:
    page = locator_page(annotation.locator)
    if page is not None:
        return f"p. {page}"
    return f"{round(float(annotation.locator.get('progress', 0)) * 100)}%"


def _block(prefix: str, text: str) -> list[str]:
    return [f"{INDENT}{prefix}{line}" for line in text.splitlines() or [""]]


def render_annotation(annotation: Annotation) -> list[str]:
    """The Markdown lines of one annotation: kind, colour, place, quote and note."""
    lines = [f"- **{annotation.kind.value}** ({annotation.color.value}, {_where(annotation)})"]
    if annotation.quote:
        lines += _block("> ", annotation.quote)
    if annotation.note:
        lines += _block("", annotation.note)
    return lines


class ExportAnnotations:
    """Markdown of the actor's own annotations, grouped by item title."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, *, item_id: UUID | None = None) -> str:
        """The export of one item or of everything; empty text when there is none."""
        async with self.uow_factory() as uow:
            annotations = await uow.annotations.list_for_user(
                actor.user_id, item_id=item_id
            )
            items = await uow.items.get_many({a.item_id for a in annotations})
        grouped: dict[UUID, list[Annotation]] = {}
        for annotation in annotations:
            grouped.setdefault(annotation.item_id, []).append(annotation)

        def title(identifier: UUID) -> str:
            item = items.get(identifier)
            return item.title if item else str(identifier)

        lines: list[str] = []
        for identifier in sorted(grouped, key=lambda i: title(i).casefold()):
            lines += [f"# {title(identifier)}", ""]
            for annotation in sorted(grouped[identifier], key=_position):
                lines += render_annotation(annotation)
            lines.append("")
        return "\n".join(lines)

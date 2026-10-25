"""Validation of the student's edits of a slide deck (`PUT …/slides`, § 3.4.6).

The student edits titles and bullets, reorders and deletes slides. Every slide is
checked again with the rules of generation, but with the generous `EDIT_LIMITS`, so
the student's own words are not cut; the ids stay, the refs are kept only when they
exist in the artifact's `refs_index`.
"""

import re
from typing import Any, Final

from app.modules.notebooks.domain.artifacts.kind_support import refs_among
from app.modules.notebooks.domain.artifacts.kinds.slides import (
    EDIT_LIMITS,
    SlideOut,
    repair_slide,
    slide_refs,
)
from app.modules.notebooks.domain.errors import OutputInvalidError

from pydantic import ValidationError

MIN_EDIT_SLIDES: Final = 1
MAX_EDIT_SLIDES: Final = 40
_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _edited_slide(
    raw: Any, number: int, labels: set[str] | None, seen: set[str]
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the repaired slide, or the problem that makes it unusable."""
    try:
        slide = SlideOut.model_validate(raw)
    except ValidationError:
        return None, f"slide {number}: not a slide"
    slide_id = (slide.id or "").strip()
    if not _ID.fullmatch(slide_id) or slide_id in seen:
        return None, f"slide {number}: the id is missing, invalid or repeated"
    seen.add(slide_id)
    body = repair_slide(slide, EDIT_LIMITS)
    if body is None:
        return None, f"slide {number}: layout {slide.layout} lacks its fields"
    refs = refs_among(slide_refs(slide), labels)
    return {"id": slide_id, **body, "refs": refs}, None


def validate_slides_edit(
    slides: list[dict[str, Any]], pack_labels: set[str] | None
) -> list[dict[str, Any]]:
    """Return the edited deck, checked and trimmed like a generated one.

    `pack_labels` are the keys of the artifact's `refs_index`; a ref that is not in
    the set is removed. ``None`` means the set is unknown: well-formed labels stay.
    Raises `OutputInvalidError` (with the problems) when the number of slides is not
    1 to 40 or a slide cannot be repaired.
    """
    if not MIN_EDIT_SLIDES <= len(slides) <= MAX_EDIT_SLIDES:
        raise OutputInvalidError(
            [f"a deck has {MIN_EDIT_SLIDES} to {MAX_EDIT_SLIDES} slides"]
        )
    problems: list[str] = []
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for number, raw in enumerate(slides, start=1):
        slide, problem = _edited_slide(raw, number, pack_labels, seen)
        if slide is not None:
            result.append(slide)
        elif problem is not None:
            problems.append(problem)
    if problems:
        raise OutputInvalidError(problems)
    return result

"""Handlers by kind. Each module in `kinds/` exports a module-level `HANDLER`."""

import importlib
from functools import cache

from app.modules.notebooks.domain.artifacts.handler import ArtifactHandler
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError

_MODULES: dict[ArtifactKind, str] = {
    ArtifactKind.REPORT: "report",
    ArtifactKind.MIND_MAP: "mind_map",
    ArtifactKind.FLASHCARDS: "flashcards",
    ArtifactKind.QUIZ: "quiz",
    ArtifactKind.DATA_TABLE: "data_table",
    ArtifactKind.SLIDES: "slides",
    ArtifactKind.INFOGRAPHIC: "infographic",
    ArtifactKind.EXERCISE: "exercise",
    ArtifactKind.COURSE_PLAN: "course_plan",
    ArtifactKind.LESSON_DRAFT: "lesson_draft",
}
_PACKAGE = "app.modules.notebooks.domain.artifacts.kinds"


def supported_kinds() -> frozenset[ArtifactKind]:
    """Kinds this build can generate (no audio or video overview, by decision)."""
    return frozenset(_MODULES)


@cache
def handler_for(kind: ArtifactKind) -> ArtifactHandler:
    """Return the handler of a kind; unsupported kinds are invalid options."""
    name = _MODULES.get(kind)
    if name is None:
        raise InvalidOptionsError(
            params={"kind": kind.value}, support_details="unsupported kind"
        )
    module = importlib.import_module(f"{_PACKAGE}.{name}")
    handler: ArtifactHandler = module.HANDLER
    return handler

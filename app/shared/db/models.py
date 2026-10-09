"""Import every module's ORM package so Base.metadata is complete."""

import importlib

from app.shared.db.base import Base

MODULES = (
    "identity",
    "academic",
    "files",
    "links",
    "notify",
    "admin",
    "ai",
    "flashcards",
    "mail",
    "lms",
    "notebooks",
    "library",
    "vectors",
)


def _import_orm(module: str) -> None:
    path = f"app.modules.{module}.infrastructure.orm"
    try:
        importlib.import_module(path)
    except ModuleNotFoundError as exc:
        # Only a missing ORM package is tolerated; a broken import inside it is not.
        if exc.name is None or not path.startswith(exc.name):
            raise


for _module in MODULES:
    _import_orm(_module)

__all__ = ["MODULES", "Base"]

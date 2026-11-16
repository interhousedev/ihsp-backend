"""Every module's personal-data specs, for the export and the erasure of a user."""

import importlib
from collections.abc import Sequence

from app.shared.personal_data import PersonalData, PersonalTable, SqlPersonalData

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MODULES = (
    "academic",
    "admin",
    "admission",
    "ai",
    "certificates",
    "dashboard",
    "faces",
    "feedback",
    "files",
    "flashcards",
    "identity",
    "knowledge",
    "legal",
    "library",
    "links",
    "lms",
    "mail",
    "notebooks",
    "notify",
    "onboarding",
    "privacy",
)


def all_specs() -> list[PersonalTable]:
    """The ``SPECS`` of every module."""
    specs: list[PersonalTable] = []
    for module in MODULES:
        loaded = importlib.import_module(
            f"app.modules.{module}.infrastructure.personal_data"
        )
        specs.extend(loaded.SPECS)
    return specs


def build_sources(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[Sequence[PersonalData], Sequence[PersonalData]]:
    """Return (export source, erase source).

    The erase source leaves out tables that ``<module>.delete_owner`` erases, because
    those tasks also delete the objects the rows point to.
    """
    specs = all_specs()
    return (
        [SqlPersonalData(sessionmaker, specs)],
        [SqlPersonalData(sessionmaker, [s for s in specs if not s.erased_elsewhere])],
    )

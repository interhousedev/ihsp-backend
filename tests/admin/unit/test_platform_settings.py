"""Platform settings: validation, defaults and the admin-only service."""

from typing import Any
from uuid import UUID

from app.modules.admin.application.platform_settings import PlatformSettingsService
from app.modules.admin.domain.platform_settings import (
    PlatformSettings,
    PlatformSettingsInvalidError,
    apply_changes,
    from_stored,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id

import pytest


class MemoryStore:
    """Implements PlatformSettingsStore."""

    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}
        self.updated_by: UUID | None = None

    async def read_all(self) -> dict[str, Any]:
        return dict(self.rows)

    async def write(self, values: dict[str, Any], *, updated_by: UUID) -> None:
        self.rows.update(values)
        self.updated_by = updated_by


ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
TEACHER = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))


async def test_defaults_when_nothing_is_saved() -> None:
    """A fresh install reads the defaults."""
    service = PlatformSettingsService(MemoryStore())

    assert await service.get(ADMIN) == PlatformSettings()
    assert PlatformSettings().change_password_on_login is False
    assert PlatformSettings().default_language == "ru"


async def test_update_saves_and_trims_and_keeps_the_rest() -> None:
    """Texts are trimmed; keys not given keep their value; the editor is recorded."""
    store = MemoryStore()
    service = PlatformSettingsService(store)

    await service.update(ADMIN, {"school_name": "  IHSU  ", "default_language": "uz"})
    updated = await service.update(ADMIN, {"change_password_on_login": True})

    assert updated.school_name == "IHSU"
    assert updated.default_language == "uz"
    assert updated.change_password_on_login is True
    assert store.updated_by == ADMIN.user_id
    assert (await service.get(ADMIN)).support_contact == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"school_name": "x" * 121},
        {"support_contact": "y" * 256},
        {"school_name": 5},
        {"change_password_on_login": "yes"},
        {"default_language": "de"},
        {"unknown_key": 1},
    ],
)
async def test_invalid_values_are_refused_and_nothing_is_saved(
    changes: dict[str, Any],
) -> None:
    """Wrong type, length, language or key: no write."""
    store = MemoryStore()

    with pytest.raises(PlatformSettingsInvalidError):
        await PlatformSettingsService(store).update(ADMIN, changes)

    assert store.rows == {}


async def test_only_administration_reads_or_writes() -> None:
    """A teacher gets 403 on both calls."""
    service = PlatformSettingsService(MemoryStore())

    with pytest.raises(ForbiddenError):
        await service.get(TEACHER)
    with pytest.raises(ForbiddenError):
        await service.update(TEACHER, {"school_name": "x"})


def test_a_broken_stored_value_falls_back_to_the_default() -> None:
    """Hand-edited rows never break the page."""
    stored = {"default_language": "xx", "school_name": "IHSU", "gone": 1}

    assert from_stored(stored) == apply_changes(
        PlatformSettings(), {"school_name": "IHSU"}
    )

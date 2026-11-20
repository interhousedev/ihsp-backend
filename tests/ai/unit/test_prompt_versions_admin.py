"""Prompt admin: stored diff and size on save, the version list and the diff."""

from uuid import uuid4

from app.modules.ai.application.prompt_registry import (
    PromptAdmin,
    PromptInvalidError,
    PromptNotFoundError,
    PromptRegistry,
)
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.shared.actor import Actor, Role
from tests.fakes.ai.requests import (
    FakePromptDefaults,
    FakePromptVersions,
    FakePublishUnit,
    FakeRequests,
)
from tests.fakes.clock import FixedClock

import pytest

SLOT = PromptSlot("chat", "intro", "Intro", "You are a helper.\nBe kind.")
ADMIN = Actor(user_id=uuid4(), roles=frozenset({Role.ADMIN}))


class Loader:
    """No active versions are read here."""

    async def active(self) -> list:
        """Nothing."""
        return []


def make() -> tuple[PromptAdmin, FakePromptVersions]:
    """An admin over in-memory versions."""
    versions = FakePromptVersions()
    audits: list = []
    admin = PromptAdmin(
        PromptRegistry([SLOT], Loader()),
        lambda: FakePublishUnit(versions, FakePromptDefaults(), FakeRequests(), audits),
        FixedClock(),
    )
    return admin, versions


async def test_put_version_stores_source_size_and_diff_against_the_builtin() -> None:
    """The first edit is diffed against the built-in (v0)."""
    admin, _ = make()

    saved = await admin.put_version(
        ADMIN, "chat", "intro", text="You are a helper.\nBe brief."
    )

    assert saved.source == "admin"
    assert saved.chars == len("You are a helper.\nBe brief.") and saved.tokens_est == 7
    assert saved.diff is not None
    assert "--- v0" in saved.diff and "+++ v1" in saved.diff
    assert "-Be kind." in saved.diff and "+Be brief." in saved.diff


async def test_put_version_diffs_against_the_previous_active_version() -> None:
    """A later edit is diffed against the active text it replaces."""
    admin, _ = make()
    await admin.put_version(ADMIN, "chat", "intro", text="One.")

    second = await admin.put_version(ADMIN, "chat", "intro", text="Two.")

    assert second.diff is not None
    assert "--- v1" in second.diff and "-One." in second.diff and "+Two." in second.diff


async def test_versions_lists_the_locale_newest_first() -> None:
    """The list has every stored version of the locale, without other locales."""
    admin, _ = make()
    await admin.put_version(ADMIN, "chat", "intro", text="One.")
    await admin.put_version(ADMIN, "chat", "intro", text="Uz.", locale="uz")
    await admin.put_version(ADMIN, "chat", "intro", text="Two.")

    found = await admin.versions(ADMIN, "chat", "intro", "")

    assert [v.version for v in found] == [3, 1]
    with pytest.raises(PromptNotFoundError):
        await admin.versions(ADMIN, "chat", "nothing", "")


async def test_diff_defaults_to_the_latest_and_its_predecessor() -> None:
    """With no bounds the diff is previous -> latest, with the size change."""
    admin, _ = make()
    await admin.put_version(ADMIN, "chat", "intro", text="One.")
    await admin.put_version(ADMIN, "chat", "intro", text="One. Two.")

    result = await admin.diff(ADMIN, "chat", "intro", locale="")

    assert (result.from_version, result.to_version) == (1, 2)
    assert result.chars_delta == 5 and "+One. Two." in result.diff
    assert result.tokens_delta == 2


async def test_diff_can_start_at_the_builtin_and_rejects_bad_ranges() -> None:
    """Version 0 is the built-in; from must be lower than to; unknown is missing."""
    admin, _ = make()
    await admin.put_version(ADMIN, "chat", "intro", text="Changed.")

    from_builtin = await admin.diff(ADMIN, "chat", "intro", locale="", from_version=0)

    assert from_builtin.from_version == 0 and "-Be kind." in from_builtin.diff
    with pytest.raises(PromptInvalidError):
        await admin.diff(
            ADMIN, "chat", "intro", locale="", from_version=1, to_version=1
        )
    with pytest.raises(PromptNotFoundError):
        await admin.diff(
            ADMIN, "chat", "intro", locale="", from_version=0, to_version=9
        )

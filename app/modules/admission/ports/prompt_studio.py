"""Port: the prompt registry as the prompt studio sees it."""

from typing import Protocol

from app.modules.admission.domain.prompt_studio import (
    PromptIssue,
    PromptVersionInfo,
    SlotInfo,
    SlotState,
    StudioSlot,
)
from app.shared.actor import Actor


class PromptStudioAdmin(Protocol):
    """Reads and writes prompt versions of the whitelisted slots."""

    async def info(self, slot: StudioSlot) -> SlotInfo | None:
        """The registry's description of a slot, None when unregistered."""
        ...

    async def state(self, actor: Actor, slot: StudioSlot, locale: str) -> SlotState:
        """The slot with its active text and versions."""
        ...

    async def check(self, slot: StudioSlot, text: str) -> tuple[PromptIssue, ...]:
        """Validate a draft without saving it."""
        ...

    async def put_version(
        self, actor: Actor, slot: StudioSlot, *, text: str, locale: str, note: str
    ) -> PromptVersionInfo:
        """Store a new version and activate it."""
        ...

    async def activate(
        self, actor: Actor, slot: StudioSlot, version: int
    ) -> PromptVersionInfo:
        """Make a stored version the active one."""
        ...

    async def revert(self, actor: Actor, slot: StudioSlot, locale: str) -> None:
        """Drop the override so the built-in text applies again."""
        ...

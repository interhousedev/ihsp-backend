"""Adapter: the admission prompt studio over the AI prompt registry."""

from app.modules.admission.domain.prompt_studio import (
    ActivePrompt,
    PromptIssue,
    PromptVersionInfo,
    SlotInfo,
    SlotState,
    StudioSlot,
    prompt_issues,
)
from app.modules.ai.application.prompt_registry import PromptAdmin
from app.modules.ai.domain.prompt_registry import PromptVersion, check_override
from app.shared.actor import Actor


def _info(version: PromptVersion) -> PromptVersionInfo:
    return PromptVersionInfo(
        version=version.version,
        locale=version.locale,
        text=version.text,
        hash=version.hash,
        active=version.active,
        note=version.note,
        created_at=version.created_at,
    )


class AiPromptStudioAdmin:
    """Reads and writes the studio's slots through `PromptAdmin`."""

    def __init__(self, admin: PromptAdmin) -> None:
        """Keep the registry administration service."""
        self._admin = admin

    async def info(self, slot: StudioSlot) -> SlotInfo | None:
        """The registry's description of a slot, None when unregistered."""
        found = self._admin.registry.slot(slot.task.value, slot.name)
        if found is None:
            return None
        return SlotInfo(
            task=found.task,
            name=found.name,
            summary=found.summary,
            template=found.template,
            fields=tuple(sorted(found.fields)),
            builtin=found.builtin,
        )

    async def state(self, actor: Actor, slot: StudioSlot, locale: str) -> SlotState:
        """The slot with its active text and versions."""
        detail = await self._admin.detail(actor, slot.task.value, slot.name, locale)
        info = await self.info(slot)
        assert info is not None  # detail() raised PromptNotFoundError otherwise
        current = detail.current
        return SlotState(
            slot=info,
            active=ActivePrompt(current.text, current.version, current.hash),
            versions=tuple(_info(v) for v in detail.versions),
        )

    async def check(self, slot: StudioSlot, text: str) -> tuple[PromptIssue, ...]:
        """Validate a draft without saving it."""
        found = self._admin.registry.slot(slot.task.value, slot.name)
        reason = check_override(found, text) if found is not None else "empty"
        return prompt_issues(reason, text)

    async def put_version(
        self, actor: Actor, slot: StudioSlot, *, text: str, locale: str, note: str
    ) -> PromptVersionInfo:
        """Store a new version and activate it."""
        return _info(
            await self._admin.put_version(
                actor, slot.task.value, slot.name, text=text, locale=locale, note=note
            )
        )

    async def activate(
        self, actor: Actor, slot: StudioSlot, version: int
    ) -> PromptVersionInfo:
        """Make a stored version the active one."""
        return _info(
            await self._admin.activate(actor, slot.task.value, slot.name, version)
        )

    async def revert(self, actor: Actor, slot: StudioSlot, locale: str) -> None:
        """Drop the override so the built-in text applies again."""
        await self._admin.revert(actor, slot.task.value, slot.name, locale)

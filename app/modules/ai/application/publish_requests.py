"""Publishing the code's prompt defaults and request registry at startup.

Runs once per deploy in the api process under a Postgres advisory lock. For every
prompt slot whose built-in text changed since the last publish, a `source='code'`
version is stored, diffed against the previously published built-in text. It becomes
the active version when the slot has no active version or its active one is also a
code version, so an administrator's text is never overwritten. Then every declared
request is upserted and the requests no code declares any more are retired.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.modules.ai.domain.prompt_registry import (
    BUILT_IN_VERSION,
    PromptSlot,
    PromptVersion,
    prompt_hash,
)
from app.modules.ai.domain.requests import (
    AiRequestSpec,
    estimate_tokens,
    unified_diff,
)
from app.modules.ai.ports.prompts import PromptVersionRepository
from app.modules.ai.ports.requests import (
    AiRequestRepository,
    PromptDefault,
    PromptDefaultRepository,
    RequestRecord,
)
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

AUDIT_PROMPT_DEFAULT_PUBLISHED = "admin.prompt_default_published"
CODE_NOTE = "code default"


class PublishUnitOfWork(Protocol):
    """One transaction over the prompt versions, defaults and the request registry."""

    @property
    def prompts(self) -> PromptVersionRepository:
        """The prompt versions of the transaction."""
        ...

    @property
    def defaults(self) -> PromptDefaultRepository:
        """The prompt defaults of the transaction."""
        ...

    @property
    def requests(self) -> AiRequestRepository:
        """The request registry of the transaction."""
        ...

    async def try_lock(self) -> bool:
        """Take the publish lock for this transaction; False: another replica has it."""
        ...

    def audit(self, draft: AuditDraft) -> None:
        """Queue an audit event for the commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the transaction."""
        ...


@dataclass(frozen=True, slots=True)
class PublishReport:
    """What one publish changed (for the startup log)."""

    prompts_published: int
    requests_registered: int
    requests_retired: int


class RequestPublisher:
    """Publishes the code's prompt defaults and request registry."""

    def __init__(
        self,
        uow_factory: Callable[[], PublishUnitOfWork],
        clock: Clock,
    ) -> None:
        """Keep the transaction factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def publish(
        self, slots: Sequence[PromptSlot], specs: Sequence[AiRequestSpec]
    ) -> PublishReport:
        """Publish changed built-in texts and sync the registry in one transaction."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            if not await uow.try_lock():
                return PublishReport(0, 0, 0)
            published = 0
            for slot in slots:
                if await self._publish_slot(uow, slot, now):
                    published += 1
            registered = 0
            for spec in specs:
                default = await uow.defaults.get(spec.template.task, spec.template.name)
                await uow.requests.upsert(
                    RequestRecord(
                        id=spec.id,
                        owner_app=spec.owner_app,
                        task=spec.task,
                        template_id=spec.template_id,
                        pipeline=spec.pipeline,
                        args_schema=spec.args_schema,
                        tools=spec.tools,
                        summary=spec.summary,
                        published_at=now,
                        retired=False,
                        code_version=default.version if default else BUILT_IN_VERSION,
                    )
                )
                registered += 1
            retired = await uow.requests.retire_except({s.id for s in specs})
            await uow.commit()
        return PublishReport(published, registered, retired)

    async def _publish_slot(
        self, uow: PublishUnitOfWork, slot: PromptSlot, now: datetime
    ) -> bool:
        """Store the slot's built-in text when it changed; True when a version was."""
        text = slot.builtin
        digest = prompt_hash(text)
        current = await uow.defaults.get(slot.task, slot.name)
        if current is not None and current.hash == digest:
            return False
        history = await uow.prompts.history(slot.task, slot.name)
        if current is None and not history:
            # First publish of a slot nobody has edited: the built-in is version 0.
            await uow.defaults.upsert(
                PromptDefault(slot.task, slot.name, BUILT_IN_VERSION, digest, text),
                now,
            )
            return False
        number = await uow.prompts.next_version(slot.task)
        diff = None
        if current is not None and current.text:
            diff = unified_diff(current.text, text, f"v{current.version}", f"v{number}")
        active = await uow.prompts.active(slot.task)
        slot_active = next(
            (v for v in active if v.name == slot.name and v.locale == ""), None
        )
        takes_over = slot_active is None or slot_active.source == "code"
        await uow.prompts.add(
            PromptVersion(
                id=new_id(),
                task=slot.task,
                name=slot.name,
                locale="",
                version=number,
                text=text,
                hash=digest,
                active=False,
                created_at=now,
                created_by=None,
                note=CODE_NOTE,
                source="code",
                diff=diff,
                chars=len(text),
                tokens_est=estimate_tokens(text),
            )
        )
        if takes_over:
            await uow.prompts.activate(slot.task, slot.name, "", number)
        await uow.defaults.upsert(
            PromptDefault(slot.task, slot.name, number, digest, text), now
        )
        uow.audit(
            AuditDraft(
                type=AUDIT_PROMPT_DEFAULT_PUBLISHED,
                actor_id=None,
                metadata={"task": slot.task, "name": slot.name, "version": number},
            )
        )
        return True

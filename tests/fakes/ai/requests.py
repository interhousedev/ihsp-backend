"""In-memory fakes of the request registry, prompt defaults and the publish unit."""

from dataclasses import replace
from datetime import datetime
from types import TracebackType
from typing import Self

from app.modules.ai.domain.prompt_registry import PromptVersion
from app.modules.ai.ports.requests import PromptDefault, RequestRecord
from app.shared.notifications import AuditDraft


class FakePromptVersions:
    """Implements the prompt version repository in memory."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[PromptVersion] = []

    async def history(self, task: str, name: str) -> list[PromptVersion]:
        """Every version of the slot, newest first."""
        found = [v for v in self.rows if v.task == task and v.name == name]
        return sorted(found, key=lambda v: v.version, reverse=True)

    async def get_version(
        self, task: str, name: str, locale: str, version: int
    ) -> PromptVersion | None:
        """One version of the slot and locale, or None."""
        return next(
            (
                v
                for v in self.rows
                if (v.task, v.name, v.locale, v.version)
                == (task, name, locale, version)
            ),
            None,
        )

    async def active(self, task: str | None = None) -> list[PromptVersion]:
        """The active versions (of one task when given)."""
        return [v for v in self.rows if v.active and (task is None or v.task == task)]

    async def next_version(self, task: str) -> int:
        """One more than the task's highest version."""
        numbers = [v.version for v in self.rows if v.task == task]
        return (max(numbers) if numbers else 0) + 1

    async def add(self, version: PromptVersion) -> None:
        """Insert a version, inactive."""
        self.rows.append(replace(version, active=False))

    async def activate(self, task: str, name: str, locale: str, version: int) -> bool:
        """Make one version the only active one of its slot and locale."""
        await self.deactivate(task, name, locale)
        for index, row in enumerate(self.rows):
            if (row.task, row.name, row.locale, row.version) == (
                task,
                name,
                locale,
                version,
            ):
                self.rows[index] = replace(row, active=True)
                return True
        return False

    async def deactivate(self, task: str, name: str, locale: str) -> int:
        """Turn off the slot's active version for the locale."""
        count = 0
        for index, row in enumerate(self.rows):
            if row.task == task and row.name == name and row.locale == locale:
                if row.active:
                    self.rows[index] = replace(row, active=False)
                    count += 1
        return count


class FakePromptDefaults:
    """Implements the prompt default repository in memory."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[tuple[str, str], PromptDefault] = {}

    async def get(self, task: str, name: str) -> PromptDefault | None:
        """The stored default of the slot, or None."""
        return self.rows.get((task, name))

    async def upsert(self, default: PromptDefault, updated_at: datetime) -> None:
        """Insert or replace the default of the slot."""
        self.rows[(default.task, default.name)] = default


class FakeRequests:
    """Implements the request registry in memory."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[str, RequestRecord] = {}

    async def list(
        self,
        *,
        owner_app: str | None = None,
        pipeline: str | None = None,
        include_retired: bool = False,
    ) -> list[RequestRecord]:
        """The registered requests, filtered."""
        return sorted(
            (
                r
                for r in self.rows.values()
                if (include_retired or not r.retired)
                and (owner_app is None or r.owner_app == owner_app)
                and (pipeline is None or r.pipeline == pipeline)
            ),
            key=lambda r: r.id,
        )

    async def get(self, request_id: str) -> RequestRecord | None:
        """One registered request, or None."""
        return self.rows.get(request_id)

    async def upsert(self, record: RequestRecord) -> None:
        """Insert or replace a request by id."""
        self.rows[record.id] = record

    async def retire_except(self, request_ids: set[str]) -> int:
        """Retire the requests not listed; how many changed."""
        count = 0
        for key, row in list(self.rows.items()):
            if key not in request_ids and not row.retired:
                self.rows[key] = replace(row, retired=True)
                count += 1
        return count


class FakePublishUnit:
    """One fake publish transaction: the three repositories and the audit queue."""

    def __init__(
        self,
        prompts: FakePromptVersions,
        defaults: FakePromptDefaults,
        requests: FakeRequests,
        audits: list[AuditDraft],
        *,
        lock_free: bool = True,
    ) -> None:
        """Share the stores across transactions; `lock_free` False: another replica."""
        self.prompts = prompts
        self.defaults = defaults
        self.requests = requests
        self.audits = audits
        self.queued: list[AuditDraft] = []
        self.committed = False
        self.lock_free = lock_free

    async def try_lock(self) -> bool:
        """Take the publish lock unless another replica holds it."""
        return self.lock_free

    def audit(self, draft: AuditDraft) -> None:
        """Queue an audit event; it is kept only on commit."""
        self.queued.append(draft)

    async def commit(self) -> None:
        """Keep the queued audit events."""
        self.audits.extend(self.queued)
        self.committed = True

    async def __aenter__(self) -> Self:
        """Open the fake transaction."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to close."""

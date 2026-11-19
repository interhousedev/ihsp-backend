"""In-memory fakes for the prompt studio tests."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.prompt_studio import PromptStudioService
from app.modules.admission.domain.essay_reviews import EssayInput
from app.modules.admission.domain.prompt_studio import (
    ActivePrompt,
    PromptIssue,
    PromptVersionInfo,
    SlotInfo,
    SlotState,
    StudioRun,
    StudioSlot,
)
from app.modules.admission.ports.ai import PromptSource
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from tests.admission.unit.fakes import NOW, FakeStore, FakeUow
from tests.fakes.clock import FixedClock

BAD = "uses {unknown} field"


class FakeExemplars:
    """Exemplars by id."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    def add(self, exemplar_id: UUID) -> None:
        self.rows[exemplar_id] = SimpleNamespace(
            id=exemplar_id,
            title="Sample",
            prompt="Why us?",
            body="An exemplar essay.",
            kind="personal_statement",
        )

    async def get(self, exemplar_id: UUID) -> Any:
        return self.rows.get(exemplar_id)


class FakeStudioUow(FakeUow):
    """FakeUow with the exemplar repository."""

    def __init__(self, s: FakeStore, exemplars: FakeExemplars) -> None:
        super().__init__(s)
        self.exemplars = exemplars


def _version(version: int, text: str = "t") -> PromptVersionInfo:
    return PromptVersionInfo(version, "", text, "h", True, "", NOW)


class FakeStudioAdmin:
    """Records the actor and arguments of every write."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Actor, tuple[Any, ...]]] = []

    async def info(self, slot: StudioSlot) -> SlotInfo | None:
        return SlotInfo(slot.task.value, slot.name, "s", False, (), "builtin")

    async def state(self, actor: Actor, slot: StudioSlot, locale: str) -> SlotState:
        info = await self.info(slot)
        assert info is not None
        return SlotState(info, ActivePrompt("active text", 0, "h"), ())

    async def check(self, slot: StudioSlot, text: str) -> tuple[PromptIssue, ...]:
        if not text:
            return (PromptIssue("error", "empty"),)
        if text == BAD:
            return (PromptIssue("error", "unknown_placeholder"),)
        return (PromptIssue("warning", "missing_fairness"),)

    async def put_version(
        self, actor: Actor, slot: StudioSlot, *, text: str, locale: str, note: str
    ) -> PromptVersionInfo:
        self.calls.append(("put", actor, (slot.name, text, locale, note)))
        return _version(1, text)

    async def activate(
        self, actor: Actor, slot: StudioSlot, version: int
    ) -> PromptVersionInfo:
        self.calls.append(("activate", actor, (slot.name, version)))
        return _version(version)

    async def revert(self, actor: Actor, slot: StudioSlot, locale: str) -> None:
        self.calls.append(("revert", actor, (slot.name, locale)))


class FakeRunner:
    """Scores 80 with the draft text and 70 with the active one."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self,
        slot: StudioSlot,
        *,
        prompts: PromptSource,
        essay: EssayInput,
        uni: Any,
        locale: str,
    ) -> StudioRun:
        self.calls += 1
        text = await prompts.text(slot.task, slot.name, locale)
        score = 80 if text == "draft" else 70
        return StudioRun("fake-model", {"score": score, "band": "B"})


class FakeLimiter:
    """Counts hits and refuses past the limit."""

    def __init__(self) -> None:
        self.count = 0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.count += 1
        if self.count > limit:
            raise RateLimitedError(params={"retry_after": 1})
        return self.count


class ActivePrompts:
    """The normal prompt source."""

    async def text(self, task: Any, name: str, locale: str) -> str:
        return "active text"


class Studio:
    """The service with all its fakes."""

    def __init__(self, store: FakeStore) -> None:
        self.exemplars = FakeExemplars()
        self.admin = FakeStudioAdmin()
        self.runner = FakeRunner()
        self.limiter = FakeLimiter()
        self.uni_calls: list[UUID] = []
        self.service = PromptStudioService(
            self.admin,
            self.runner,
            ActivePrompts(),
            lambda: FakeStudioUow(store, self.exemplars),
            FixedClock(NOW),
            self.limiter,  # type: ignore[arg-type]
            uni_loader=self._uni,
        )

    async def _uni(self, uow: Any, institution_id: UUID) -> Any:
        self.uni_calls.append(institution_id)
        return None if institution_id == UUID(int=0) else SimpleNamespace()

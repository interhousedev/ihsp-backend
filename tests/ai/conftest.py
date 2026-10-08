"""Fixtures of the AI tests: the module wired to fakes."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.ports.turn_lock import TurnLock
from app.modules.ai.ports.unit_of_work import UowFactory
from app.modules.ai.wiring import AiOverrides, AiServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.ai import LlmGateway
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import (
    FakeAdminBackend,
    FakeClasswork,
    FakeFiles,
    FakeFlashcards,
    FakeIdentity,
    FakeLinks,
    FakeMarks,
    FakeSchedule,
    make_user,
)
from tests.fakes.ai.llm import ScriptedLlm
from tests.fakes.ai.stores import (
    InMemoryBudgetStore,
    InMemorySummaryStore,
    InMemoryTurnLock,
)
from tests.fakes.ai.uow import FakeAiStore, fake_uow_factory
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class AiHarness:
    """The wired module with every fake reachable for arrangement and assertions."""

    services: AiServices
    store: FakeAiStore
    llm: ScriptedLlm
    budget: InMemoryBudgetStore
    summaries: InMemorySummaryStore
    marks: FakeMarks
    classwork: FakeClasswork
    schedule: FakeSchedule
    files: FakeFiles
    flashcards: FakeFlashcards
    links: FakeLinks
    admin_backend: FakeAdminBackend
    clock: FixedClock
    student: Actor
    admin: Actor
    other_student: Actor
    settings: Settings

    async def new_chat(
        self, actor: Actor | None = None, assistant: Assistant = Assistant.STUDENT
    ) -> Any:
        """Create a chat and return its view."""
        who = actor or (self.student if assistant is Assistant.STUDENT else self.admin)
        return await self.services.create_chat.execute(actor=who, assistant=assistant)

    async def say(
        self, chat_id: Any, text: str, *, actor: Actor | None = None, files: Any = None
    ) -> Any:
        """Send a message as the student (or the given actor)."""
        return await self.services.send_message.execute(
            actor=actor or self.student,
            chat_id=chat_id,
            text=text,
            file_ids=files or [],
        )


HarnessFactory = Callable[..., AiHarness]


@pytest.fixture
def make_harness(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> HarnessFactory:
    """Factory of harnesses; options replace the model, limits, lock or unit of work."""

    def factory(
        *,
        llm: LlmGateway | None = None,
        limits: dict[str, int] | None = None,
        lock: TurnLock | None = None,
        uow_factory: UowFactory | None = None,
    ) -> AiHarness:
        student_user = make_user(Role.STUDENT, first="Aziza", last="Karimova")
        other_user = make_user(Role.STUDENT, first="Bobur", last="Rashidov")
        admin_user = make_user(Role.ADMIN, first="Dilnoza", last="Saidova")
        identity = FakeIdentity(student_user, other_user, admin_user)
        cfg = settings
        if limits:
            cfg = settings.model_copy(
                update={"limits": settings.limits.model_copy(update=limits)}
            )
        scripted = ScriptedLlm()
        store, budget, summaries = (
            FakeAiStore(),
            InMemoryBudgetStore(),
            InMemorySummaryStore(),
        )
        parts = {
            "marks": FakeMarks(),
            "classwork": FakeClasswork(),
            "schedule": FakeSchedule(),
            "files": FakeFiles(),
            "flashcards": FakeFlashcards(),
            "links": FakeLinks(),
            "admin_backend": FakeAdminBackend(),
        }
        deps = ModuleDeps(
            settings=cfg,
            clock=clock,
            redis=redis,
            sessionmaker=async_sessionmaker(class_=AsyncSession),
            kicker=kicker,
            rate_limiter=RateLimiter(redis),
            i18n=i18n,
            outbox_writer=noop_outbox_writer,
            audit_writer=noop_audit_writer,
            outbox_committed_hook=None,
        )
        services = build(
            deps,
            llm=llm or scripted,
            identity=identity,
            schedule=parts["schedule"],
            classwork=parts["classwork"],
            marks=parts["marks"],
            files=parts["files"],
            flashcards=parts["flashcards"],
            admin_tools=parts["admin_backend"],
            links=parts["links"],
            overrides=AiOverrides(
                budget_store=budget,
                summary_store=summaries,
                turn_lock=lock or InMemoryTurnLock(),
                uow_factory=uow_factory or fake_uow_factory(store),
            ),
        )
        return AiHarness(
            services=services,
            store=store,
            llm=scripted,
            budget=budget,
            summaries=summaries,
            clock=clock,
            student=make_actor(Role.STUDENT, user_id=student_user.id),
            admin=make_actor(Role.ADMIN, user_id=admin_user.id),
            other_student=make_actor(Role.STUDENT, user_id=other_user.id),
            settings=cfg,
            **parts,
        )

    return factory


@pytest.fixture
def h(make_harness: HarnessFactory) -> AiHarness:
    """A harness with the scripted model and default limits."""
    return make_harness()

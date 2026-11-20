"""Publishing prompt defaults and the request registry at startup."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import uuid4

from app.modules.ai.application.publish_requests import (
    AUDIT_PROMPT_DEFAULT_PUBLISHED,
    RequestPublisher,
)
from app.modules.ai.domain.prompt_registry import PromptSlot, PromptVersion
from app.modules.ai.domain.requests import AiRequestSpec, build_catalog
from app.shared.ai_tasks import AiTask
from tests.fakes.ai.requests import (
    FakePromptDefaults,
    FakePromptVersions,
    FakePublishUnit,
    FakeRequests,
)
from tests.fakes.clock import FixedClock

SLOT = PromptSlot("studio_quiz", "main", "Quiz", "Write a quiz.\nBe brief.")


class Stores:
    """Fresh stores plus a publisher over them."""

    def __init__(self) -> None:
        """Start with empty stores."""
        self.prompts = FakePromptVersions()
        self.defaults = FakePromptDefaults()
        self.requests = FakeRequests()
        self.audits: list = []
        self.publisher = RequestPublisher(
            lambda: FakePublishUnit(
                self.prompts, self.defaults, self.requests, self.audits
            ),
            FixedClock(),
        )

    async def publish(
        self, slots: Sequence[PromptSlot], specs: Sequence[AiRequestSpec] = ()
    ):
        """Publish the slots and the declared specs."""
        return await self.publisher.publish(slots, list(specs))


def admin_version(
    slot: PromptSlot, number: int, text: str, active: bool
) -> PromptVersion:
    """A stored administrator's version of the slot."""
    return PromptVersion(
        id=uuid4(),
        task=slot.task,
        name=slot.name,
        locale="",
        version=number,
        text=text,
        hash="0" * 16,
        active=active,
        created_at=FixedClock().now(),
        note="",
        source="admin",
        chars=len(text),
        tokens_est=1,
    )


async def test_a_new_slot_gets_built_in_version_zero_and_no_version_row() -> None:
    stores = Stores()
    report = await stores.publish([SLOT])
    assert report.prompts_published == 0
    assert stores.prompts.rows == []
    default = await stores.defaults.get("studio_quiz", "main")
    assert default is not None and default.version == 0


async def test_a_changed_built_in_text_becomes_an_active_code_version_with_diff() -> (
    None
):
    stores = Stores()
    await stores.publish([SLOT])
    changed = PromptSlot("studio_quiz", "main", "Quiz", "Write a quiz.\nBe thorough.")
    report = await stores.publish([changed])
    assert report.prompts_published == 1
    (row,) = stores.prompts.rows
    assert row.source == "code"
    assert row.active is True
    assert row.version == 1
    assert "+Be thorough." in (row.diff or "")
    assert stores.audits[-1].type == AUDIT_PROMPT_DEFAULT_PUBLISHED


async def test_an_unchanged_text_publishes_nothing() -> None:
    stores = Stores()
    await stores.publish([SLOT])
    await stores.publish([SLOT])
    assert stores.prompts.rows == []
    assert stores.audits == []


async def test_a_changed_text_never_overwrites_an_administrators_active_version() -> (
    None
):
    stores = Stores()
    await stores.publish([SLOT])
    stores.prompts.rows.append(admin_version(SLOT, 1, "Admin text.", active=True))
    changed = PromptSlot("studio_quiz", "main", "Quiz", "Write a quiz.\nBe thorough.")
    await stores.publish([changed])
    active = [v for v in stores.prompts.rows if v.active]
    assert [v.source for v in active] == ["admin"]
    code = [v for v in stores.prompts.rows if v.source == "code"]
    assert len(code) == 1 and code[0].active is False


async def test_a_request_is_registered_and_one_no_code_declares_is_retired() -> None:
    stores = Stores()
    spec = AiRequestSpec(
        id="notebooks.studio_quiz.main",
        owner_app="notebooks",
        task=AiTask.STUDIO_QUIZ,
        template=SLOT,
        summary="Quiz",
    )
    await stores.publish([SLOT], build_catalog([SLOT], [spec]))
    row = stores.requests.rows["notebooks.studio_quiz.main"]
    assert row.template_id == "studio_quiz/main"
    assert row.retired is False
    assert row.code_version == 0

    await stores.publish([SLOT], build_catalog([SLOT], []))
    gone = stores.requests.rows["notebooks.studio_quiz.main"]
    assert gone.retired is True
    assert replace(gone, retired=False).id == row.id


async def test_publish_skips_when_another_replica_holds_the_lock() -> None:
    """Without the advisory lock nothing is written, so replicas never double-insert."""
    stores = Stores()
    stores.publisher = RequestPublisher(
        lambda: FakePublishUnit(
            stores.prompts,
            stores.defaults,
            stores.requests,
            stores.audits,
            lock_free=False,
        ),
        FixedClock(),
    )

    spec = AiRequestSpec(
        id="notebooks.studio_quiz.main",
        owner_app="notebooks",
        task="studio_quiz",
        template=SLOT,
    )

    report = await stores.publish([SLOT], [spec])

    assert (report.prompts_published, report.requests_registered) == (0, 0)
    assert stores.requests.rows == {} and stores.defaults.rows == {}

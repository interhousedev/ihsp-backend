"""The accept and decline buttons of a club ownership offer."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.ownership import TransferError
from app.shared.actor import Actor
from app.shared.contracts.callbacks import ClubTransferCb
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG
from tests.bot.support.harness import Harness

import pytest


@dataclass
class FakeOwnership:
    """Recipient-only answers; a second answer is a conflict."""

    recipient: UUID
    calls: list[tuple[str, UUID]] = field(default_factory=list)
    answered: bool = False

    async def _answer(self, what: str, actor: Actor, transfer_id: UUID) -> None:
        if actor.user_id != self.recipient:
            raise PermissionDeniedError()
        if self.answered:
            raise TransferError()
        self.answered = True
        self.calls.append((what, transfer_id))

    async def accept(self, actor: Actor, transfer_id: UUID, /) -> None:
        await self._answer("accept", actor, transfer_id)

    async def decline(self, actor: Actor, transfer_id: UUID, /) -> None:
        await self._answer("decline", actor, transfer_id)


@pytest.fixture
def ownership(harness: Harness) -> FakeOwnership:
    """An offer addressed to the linked student."""
    fake = FakeOwnership(recipient=harness.world.student.id)
    harness.world.container.activities.ownership = fake
    return fake


def _data(transfer: UUID, d: str) -> str:
    packed = ClubTransferCb(t=uuid_to_b64(transfer), d=d).pack()
    assert len(packed.encode()) <= 64
    return packed


async def test_accept_calls_ownership_as_the_linked_user(
    harness: Harness, ownership: FakeOwnership
) -> None:
    """The recipient's tap accepts and edits the message with the result."""
    transfer = new_id()

    await harness.press(_data(transfer, "a"), user_id=STUDENT_TG)

    assert ownership.calls == [("accept", transfer)]
    assert "club-transfer-bot-accepted" in harness.last_text()


async def test_decline(harness: Harness, ownership: FakeOwnership) -> None:
    """The recipient's refusal is passed on."""
    transfer = new_id()

    await harness.press(_data(transfer, "d"), user_id=STUDENT_TG)

    assert ownership.calls == [("decline", transfer)]
    assert "club-transfer-bot-declined" in harness.last_text()


async def test_another_user_changes_nothing(
    harness: Harness, ownership: FakeOwnership
) -> None:
    """Someone else's tap is refused."""
    await harness.press(_data(new_id(), "a"), user_id=TEACHER_TG)

    assert ownership.calls == []
    assert harness.toasts[-1].text == "club-transfer-bot-not-available"


async def test_replay_says_already_answered(
    harness: Harness, ownership: FakeOwnership
) -> None:
    """A second tap cannot change the answer."""
    transfer = new_id()
    await harness.press(_data(transfer, "d"), user_id=STUDENT_TG)
    await harness.press(_data(transfer, "a"), user_id=STUDENT_TG)

    assert ownership.calls == [("decline", transfer)]
    assert harness.toasts[-1].text == "club-transfer-bot-already-answered"

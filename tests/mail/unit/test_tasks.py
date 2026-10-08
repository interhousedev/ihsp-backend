"""The taskiq tasks of the mail module call the right use cases."""

from app.interfaces.jobs import context
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.tasks.mail.check_bounces import check_bounces
from app.interfaces.jobs.tasks.mail.parse_inbound import parse_inbound
from app.interfaces.jobs.tasks.mail.purge import purge
from app.interfaces.jobs.tasks.mail.send_outbound import send_outbound
from app.interfaces.jobs.tasks.mail.sweep import sweep
from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_status import MailStatus
from app.shared.contracts.identity import UserRef
from tests.mail.helpers import fixture_bytes, make_raw
from tests.mail.world import MailWorld

import pytest


class Container:
    """Just enough of the Container: the mail services."""

    def __init__(self, mail: MailWorld) -> None:
        self.mail = mail


@pytest.fixture(autouse=True)
def worker_container(world: MailWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a container whose `mail` services are the in-memory world."""
    monkeypatch.setattr(context, "_container", Container(world))


@pytest.mark.parametrize(
    "name",
    [
        "mail.parse_inbound",
        "mail.send_outbound",
        "mail.purge",
        "mail.check_bounces",
        "mail.sweep",
    ],
)
def test_the_task_is_registered_under_its_name(name: str) -> None:
    """MAIL-9: the names the kicker and the schedule use."""
    assert broker.find_task(name) is not None


async def test_parse_inbound_parses_the_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: mail.parse_inbound(mail_id)."""
    [mail_id] = await world.deliver(fixture_bytes("plain.eml"))

    await parse_inbound(mail_id)

    assert world.store.rows[mail_id].meta.parsed_at is not None


async def test_send_outbound_sends_the_mail(world: MailWorld, student: UserRef) -> None:
    """MAIL-6: mail.send_outbound(mail_id)."""
    mail = await world.send_mail.execute(
        student.id, to=["a@example.org"], subject="x", html="x"
    )

    await send_outbound(mail.id)

    assert world.store.rows[mail.id].status == MailStatus.SENT


async def test_purge_deletes_old_spam(world: MailWorld, student: UserRef) -> None:
    """MAIL-5: mail.purge."""
    world.authenticator.checks = InboundChecks(spf="fail")
    [spam_id] = await world.deliver(make_raw(message_id=None))
    world.clock.advance(days=31)

    await purge()

    assert spam_id not in world.store.rows


async def test_check_bounces_suspends_a_spiking_mailbox(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: mail.check_bounces."""
    for number in range(5):
        mail = await world.send_mail.execute(
            student.id, to=[f"g{number}@example.org"], subject="x", html="x"
        )
        world.store.rows[mail.id].mark_bounced(world.clock.now(), None)

    await check_bounces()

    assert student.id in world.suspension.reasons


async def test_sweep_kicks_unfinished_work(world: MailWorld, student: UserRef) -> None:
    """MAIL-9: mail.sweep."""
    await world.deliver(fixture_bytes("plain.eml"))
    world.kicker.calls.clear()
    world.clock.advance(minutes=11)

    await sweep()

    assert world.kicker.names() == ["mail.parse_inbound"]

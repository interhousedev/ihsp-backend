"""Every 10 minutes: restart parsing and sending that did not finish."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.mail.application.kicks import PARSE_INBOUND, SEND_OUTBOUND
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

STALE_AFTER = timedelta(minutes=10)
BATCH = 200


@dataclass(frozen=True, slots=True)
class SweepResult:
    """How many tasks were started again."""

    parse: int
    send: int


class SweepMail:
    """Kick again inbound mails not parsed and outbound mails not sent."""

    def __init__(
        self, *, uow_factory: UowFactory, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._kicker = kicker
        self._clock = clock

    async def execute(self) -> SweepResult:
        """Find stale rows and enqueue their tasks."""
        threshold = self._clock.now() - STALE_AFTER
        async with self._uow_factory() as uow:
            to_parse = await uow.mail.unparsed_inbound(threshold, BATCH)
            to_send = await uow.mail.stale_queued(threshold, BATCH)
        for mail_id in to_parse:
            await self._kicker.kick(PARSE_INBOUND, mail_id=mail_id)
        for mail_id in to_send:
            await self._kicker.kick(SEND_OUTBOUND, mail_id=mail_id)
        return SweepResult(parse=len(to_parse), send=len(to_send))

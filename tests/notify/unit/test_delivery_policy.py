"""Retry delays and the final status after a send round (BOT-22, UF-BOT-11)."""

from datetime import timedelta

from app.modules.notify.domain.delivery_outcome import settle, skip
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.retry_policy import next_retry_at
from app.shared.ids import new_id
from tests.factories.notify import NOW, make_notification

import pytest


@pytest.mark.parametrize(
    ("attempts", "minutes"), [(1, 1), (2, 5), (3, 30), (4, None), (0, None)]
)
def test_retry_waits_one_five_and_thirty_minutes_then_gives_up(
    attempts: int, minutes: int | None
) -> None:
    """BOT-11: a failed send is retried after 1, 5 and 30 minutes, then fails."""
    result = next_retry_at(attempts, NOW)

    assert result == (NOW + timedelta(minutes=minutes) if minutes else None)


def test_all_accounts_sent_makes_the_notification_sent() -> None:
    """BOT-11: every linked account got the message."""
    n = make_notification(new_id())
    n.record(1, DeliveryState.SENT)
    n.record(2, DeliveryState.SENT)

    settle(n, [1, 2], NOW)

    assert n.status == NotificationStatus.SENT
    assert n.sent_at == NOW
    assert n.next_attempt_at is None


def test_blocked_accounts_do_not_count_against_sent() -> None:
    """BOT-22: a blocked account is not a failure."""
    n = make_notification(new_id())
    n.record(1, DeliveryState.SENT)
    n.record(2, DeliveryState.BLOCKED)

    settle(n, [1, 2], NOW)

    assert n.status == NotificationStatus.SENT


def test_only_blocked_accounts_make_the_notification_skipped() -> None:
    """UF-BOT-11: the notification is marked skipped, not failed."""
    n = make_notification(new_id())
    n.record(1, DeliveryState.BLOCKED)

    settle(n, [1], NOW)

    assert n.status == NotificationStatus.SKIPPED


def test_a_failed_account_makes_the_notification_partial_with_a_retry_time() -> None:
    """BOT-11: failed accounts are retried later."""
    n = make_notification(new_id())
    n.record(1, DeliveryState.SENT)
    n.record(2, DeliveryState.FAILED)
    n.attempts = 1

    settle(n, [1, 2], NOW)

    assert n.status == NotificationStatus.PARTIAL
    assert n.next_attempt_at == NOW + timedelta(minutes=1)


def test_after_the_last_retry_the_notification_fails() -> None:
    """BOT-11: three retries, then failed."""
    n = make_notification(new_id())
    n.record(1, DeliveryState.FAILED)
    n.attempts = 4

    settle(n, [1], NOW)

    assert n.status == NotificationStatus.FAILED
    assert n.next_attempt_at is None


def test_skip_records_the_reason_and_clears_the_retry_time() -> None:
    """UF-BOT-04: nothing to send closes the notification."""
    n = make_notification(new_id())
    n.next_attempt_at = NOW

    skip(n, "no-telegram")

    assert n.status == NotificationStatus.SKIPPED
    assert n.error == "no-telegram"
    assert n.next_attempt_at is None

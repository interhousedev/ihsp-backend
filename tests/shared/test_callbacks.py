"""Telegram callback data stays within 64 bytes."""

from uuid import uuid4

from app.shared.contracts import callbacks
from app.shared.ids import uuid_to_b64

import pytest
from aiogram.filters.callback_data import CallbackData

LESSON = uuid_to_b64(uuid4())
LARGEST: list[CallbackData] = [
    callbacks.MenuCb(screen="homework"),
    callbacks.HomeworkDoneCb(lesson=LESSON, done=True),
    callbacks.AttToggleCb(lesson=LESSON, pos=9999),
    callbacks.AttActionCb(lesson=LESSON, action="all_present"),
    callbacks.HomeworkPromptCb(lesson=LESSON, action="cancel"),
    callbacks.ResourceLessonCb(lesson=LESSON, role="m"),
    callbacks.MailCb(mail=LESSON, action="unspam"),
    callbacks.MailListCb(before=2_000_000_000),
    callbacks.SettingsCb(key="marks_enabled", value="false"),
    callbacks.OtpCancelCb(request=LESSON),
    callbacks.NotMeCb(kind="otp"),
    callbacks.CancelCb(),
]


@pytest.mark.parametrize("data", LARGEST, ids=lambda d: type(d).__name__)
def test_callback_data_fits_telegram_and_round_trips(data: CallbackData) -> None:
    """BOT-2: the largest value packs into at most 64 bytes and unpacks equal."""
    packed = data.pack()

    assert len(packed.encode()) <= 64
    assert type(data).unpack(packed) == data


def test_prefixes_are_short_and_unique() -> None:
    """Prefixes are at most 4 characters and never repeat."""
    prefixes = [type(data).__prefix__ for data in LARGEST]

    assert all(len(prefix) <= 4 for prefix in prefixes)
    assert len(set(prefixes)) == len(prefixes)

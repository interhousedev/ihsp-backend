"""BOT-2: every CallbackData class packs to at most 64 bytes with real values."""

from uuid import uuid4

from app.interfaces.bot.callbacks import MailComposeCb
from app.shared.contracts import callbacks
from app.shared.ids import b64_to_uuid, uuid_to_b64

import pytest
from aiogram.filters.callback_data import CallbackData

LESSON = uuid_to_b64(uuid4())
LARGE = 10**9  # more than any position or unix time the bot packs

LARGEST: list[CallbackData] = [
    callbacks.MenuCb(screen="homework"),
    callbacks.HomeworkDoneCb(lesson=LESSON, done=True),
    callbacks.AttToggleCb(lesson=LESSON, pos=LARGE),
    callbacks.AttActionCb(lesson=LESSON, action="all_present"),
    callbacks.HomeworkPromptCb(lesson=LESSON, action="cancel"),
    callbacks.ResourceLessonCb(lesson=LESSON, role="m"),
    callbacks.MailCb(mail=LESSON, action="unspam"),
    callbacks.MailListCb(before=LARGE * 10),
    callbacks.SettingsCb(key="mark_below", value="off"),
    callbacks.OtpCancelCb(request=LESSON),
    callbacks.NotMeCb(kind="otp"),
    callbacks.CancelCb(),
    MailComposeCb(action="send"),
]


@pytest.mark.parametrize("data", LARGEST, ids=lambda d: type(d).__name__)
def test_callback_data_fits_the_telegram_limit(data: CallbackData) -> None:
    """BOT-2: the packed form is at most 64 bytes and unpacks to the same value."""
    packed = data.pack()

    assert len(packed.encode()) <= 64
    assert type(data).unpack(packed) == data


def test_every_callback_class_is_covered() -> None:
    """A new CallbackData class must be added to LARGEST."""
    declared = {
        cls
        for cls in vars(callbacks).values()
        if isinstance(cls, type)
        and issubclass(cls, CallbackData)
        and cls is not CallbackData
    }
    covered = {type(data) for data in LARGEST}

    assert declared <= covered


def test_packed_uuid_round_trips() -> None:
    """Callbacks carry 22 character UUIDs, not 36."""
    value = uuid4()

    assert len(uuid_to_b64(value)) == 22
    assert b64_to_uuid(uuid_to_b64(value)) == value


def test_prefixes_are_unique_and_short() -> None:
    """Prefixes identify the class, so they must not collide."""
    prefixes = [type(data).__prefix__ for data in LARGEST]

    assert len(set(prefixes)) == len(prefixes)
    assert all(len(prefix) <= 4 for prefix in prefixes)

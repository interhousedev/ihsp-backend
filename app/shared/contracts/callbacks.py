"""Telegram callback data shared by notification renderers and bot handlers.

Every prefix has at most 4 characters; UUIDs are packed with uuid_to_b64
(22 characters) and Telegram allows 64 bytes in total.
"""

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="m"):
    """Open a bot screen: today, marks, homework, mail, settings or lesson."""

    screen: str


class HomeworkDoneCb(CallbackData, prefix="hd"):
    """Mark a lesson's homework as done or not done."""

    lesson: str
    done: bool


class AttToggleCb(CallbackData, prefix="at"):
    """Toggle one student in the attendance draft."""

    lesson: str
    pos: int


class AttActionCb(CallbackData, prefix="aa"):
    """Attendance action: submit, all_present or edit."""

    lesson: str
    action: str


class HomeworkPromptCb(CallbackData, prefix="hp"):
    """Homework prompt action: add, none, save, edit, cancel or topic."""

    lesson: str
    action: str


class ResourceLessonCb(CallbackData, prefix="rl"):
    """Open lesson resources: role m (materials) or a (attachments)."""

    lesson: str
    role: str


class MailCb(CallbackData, prefix="ml"):
    """Mail action: reply, fwd, full, spam, unspam or open."""

    mail: str
    action: str


class MailListCb(CallbackData, prefix="mls"):
    """Page of the mail list; before is unix seconds, 0 means newest."""

    before: int


class SettingsCb(CallbackData, prefix="st"):
    """Change one setting."""

    key: str
    value: str


class OtpCancelCb(CallbackData, prefix="oc"):
    """Cancel a pending OTP reset (identity cancel_otp_reset)."""

    request: str


class NotMeCb(CallbackData, prefix="nm"):
    """'This was not me': kind is tg or otp."""

    kind: str


class CancelCb(CallbackData, prefix="x"):
    """Cancel the current multi-step input."""

"""Callback data used only inside the bot (not shared with notification renderers)."""

from aiogram.filters.callback_data import CallbackData


class MailComposeCb(CallbackData, prefix="mc"):
    """Mail composition step: new, send, edit or skip (the optional forward note)."""

    action: str


class WorkOffPromptCb(CallbackData, prefix="wp"):
    """Work-off step of the attendance prompt: menu, text or cancel_text."""

    lesson: str
    action: str


class WorkOffPickCb(CallbackData, prefix="wc"):
    """Pick the lesson's work-off template by position; 0 means no template."""

    lesson: str
    pos: int


class WorkOffPageCb(CallbackData, prefix="wg"):
    """Page of the teacher's open work-offs."""

    page: int


class WorkOffDoneCb(CallbackData, prefix="wd"):
    """Mark a work-off done; page is where the teacher was."""

    item: str
    page: int


class WorkOffUndoCb(CallbackData, prefix="wu"):
    """Put a work-off back to assigned; page is where the teacher was."""

    item: str
    page: int


class JournalCb(CallbackData, prefix="jn"):
    """Lesson journal: open the student list or go back to the prompt."""

    lesson: str
    action: str


class JournalStudentCb(CallbackData, prefix="js"):
    """Open the mark buttons of the student at the roster position."""

    lesson: str
    pos: int


class JournalMarkCb(CallbackData, prefix="jm"):
    """Save a temporary mark for the student; value 0 removes it."""

    lesson: str
    pos: int
    value: int

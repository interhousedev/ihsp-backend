"""Button data of the feedback flow (short prefixes, far below 64 bytes)."""

from aiogram.filters.callback_data import CallbackData


class FeedbackKindCb(CallbackData, prefix="fk"):
    """Pick the kind of the report: idea, bug or other."""

    kind: str


class FeedbackAreaCb(CallbackData, prefix="fa"):
    """Pick the area of the report (the product part it is about)."""

    area: str


class FeedbackStepCb(CallbackData, prefix="fz"):
    """Attachments done or skipped, and the summary's send."""

    action: str  # done | skip | send

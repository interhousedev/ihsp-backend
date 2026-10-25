"""The mode a Telegram user picked on /start."""

from enum import StrEnum


class BotMode(StrEnum):
    """Guest (parents, applicants) or Interhouse student (the login flow)."""

    GUEST = "guest"
    STUDENT = "student"

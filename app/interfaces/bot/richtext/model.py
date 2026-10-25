"""Output value objects of the Telegram rich text converter."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ButtonSpec:
    """An inline keyboard button; exactly one of url or callback_data is set."""

    label: str
    url: str | None = None
    callback_data: str | None = None


@dataclass(frozen=True, slots=True)
class FormulaSpec:
    """A display formula too complex for Unicode text, to be rendered as an image."""

    latex: str
    display: bool = True


@dataclass(frozen=True, slots=True)
class TelegramChunk:
    """One Telegram message in HTML parse mode, with its keyboard and image formulas."""

    text: str
    buttons: tuple[ButtonSpec, ...] = ()
    formulas: tuple[FormulaSpec, ...] = ()

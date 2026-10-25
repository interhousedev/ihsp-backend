"""Telegram rich text: AI markdown with LaTeX and buttons to Telegram HTML chunks."""

from app.interfaces.bot.richtext.buttons import callback_data_fits, parse_button_body
from app.interfaces.bot.richtext.latex import LatexResult, latex_to_unicode
from app.interfaces.bot.richtext.model import ButtonSpec, FormulaSpec, TelegramChunk
from app.interfaces.bot.richtext.render import render_partial, render_telegram

__all__ = [
    "ButtonSpec",
    "FormulaSpec",
    "LatexResult",
    "TelegramChunk",
    "callback_data_fits",
    "latex_to_unicode",
    "parse_button_body",
    "render_partial",
    "render_telegram",
]

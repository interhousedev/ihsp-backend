"""Telegram cannot render OpenUI: blocks degrade to text (AI-OPENUI)."""

from app.interfaces.bot.richtext import render_partial, render_telegram

BLOCK = (
    "```openui\n"
    "root = Stack([t])\n"
    't = Table(["Day", "Mark"], [["Mon", 5], ["Tue", 4]])\n'
    "```"
)


def test_block_becomes_text() -> None:
    """AI-OPENUI: a table block arrives as readable lines, not code."""
    html = "".join(c.text for c in render_telegram(f"Your marks:\n{BLOCK}"))
    assert "Mon | 5" in html
    assert "root =" not in html and "<pre" not in html


def test_streaming_hides_an_unfinished_block() -> None:
    """AI-OPENUI: a half-written block is not shown while streaming."""
    html = "".join(c.text for c in render_partial("Your marks:\n```openui\nroot = St"))
    assert "Your marks" in html
    assert "root" not in html

"""Deterministic prompt injection defences, independent of the model's obedience.

Untrusted data (tool results, search hits, web pages) loses instruction-like text
before the model sees it, so the model can neither obey nor repeat it. The stored
result stays intact: only the copy in the request changes. A user message that only
attacks the rules can be recognised too, see `is_rule_attack`.
"""

import re
from typing import Any, Final

REMOVED: Final = "[removed: instruction-like text]"

_APOSTROPHE: Final = "[ʼʻ'‘’`]?"
_RULES_EN: Final = r"(?:instructions?|rules?|prompts?|guidelines?|directions?)"
_RULES_RU: Final = r"(?:инструкци\w*|правил\w*|указани\w*|промпт\w*)"
_RULES_UZ: Final = rf"(?:ko{_APOSTROPHE}rsatma\w*|qoida\w*|yo{_APOSTROPHE}riqnoma\w*)"
_GAP: Final = r"[^.!?\n]{0,40}?"

_TRIGGERS: Final = tuple(
    re.compile(pattern, re.IGNORECASE | re.UNICODE)
    for pattern in (
        # English
        rf"\b(?:ignore|disregard|forget|override|bypass)\b\s+{_GAP}"
        rf"\b(?:previous|prior|above|earlier|all|your|system|any)\b{_GAP}"
        rf"\b{_RULES_EN}\b",
        r"\bsystem\s+override\b",
        rf"\b(?:print|reveal|show|repeat|output)\b\s+{_GAP}\bsystem\s+"
        r"(?:prompt|instructions?|message)\b",
        r"</?\s*(?:system|assistant)\s*>|\[/?INST\]",
        # Russian
        rf"\b(?:игнорируй\w*|проигнорируй\w*|забудь\w*|отмени\w*|не\s+следуй\w*)\s+"
        rf"{_GAP}{_RULES_RU}",
        rf"\b(?:выведи\w*|покажи\w*|раскрой\w*|повтори\w*)\s+{_GAP}"
        rf"(?:системн\w+\s+{_RULES_RU}|системн\w+\s+промпт\w*)",
        # Uzbek: the verb comes last
        rf"\b{_RULES_UZ}{_GAP}\s(?:unuting|unut|e{_APOSTROPHE}tiborsiz\s+qoldiring|"
        rf"bekor\s+qiling|e{_APOSTROPHE}tibor\s+bermang)\b",
        rf"\btizim\s+{_RULES_UZ}{_GAP}\s*(?:chiqaring|ko{_APOSTROPHE}rsating|ayting)\b",
    )
)
# With a trigger in the paragraph, these orders to the assistant go as well.
_ORDER: Final = re.compile(
    r"^\W*(?:please\s+)?(?:tell|say|reply|respond|answer|create|call|send|delete|"
    r"скажи\w*|ответь\w*|создай\w*|вызови\w*|отправь\w*|удали\w*)\b|"
    r"\b(?:ayting|javob\s+bering|yarating|yuboring|o[ʼʻ'‘’`]?chiring)\W*$",
    re.IGNORECASE | re.UNICODE,
)
_SENTENCE: Final = re.compile(r"(?<=[.!?…])\s+")
_PARAGRAPH: Final = re.compile(r"(\n\s*\n)")


def _has_trigger(text: str) -> bool:
    return any(pattern.search(text) for pattern in _TRIGGERS)


def _clean_paragraph(paragraph: str) -> str:
    """The sentences before the first trigger that are not orders, then the marker."""
    kept: list[str] = []
    for sentence in _SENTENCE.split(paragraph.strip()):
        if _has_trigger(sentence):
            break
        if not _ORDER.search(sentence):
            kept.append(sentence)
    return " ".join([*kept, REMOVED])


def neutralize_text(text: str) -> str:
    """The text without its instruction-like paragraphs' tails; else the same text.

    An injection needs not end with its trigger, so the rest of the paragraph after
    the trigger goes too. Text before it stays, unless it is an order to the assistant.
    """
    if not _has_trigger(text):
        return text
    parts = _PARAGRAPH.split(text)
    return "".join(
        _clean_paragraph(part) if _has_trigger(part) else part for part in parts
    )


def neutralize(value: Any) -> Any:
    """`neutralize_text` over every string of a JSON-like value; keys stay."""
    if isinstance(value, str):
        return neutralize_text(value)
    if isinstance(value, list | tuple):
        return [neutralize(item) for item in value]
    if isinstance(value, dict):
        return {key: neutralize(item) for key, item in value.items()}
    return value


def is_rule_attack(text: str) -> bool:
    """True when a user message tells the assistant to drop or print its rules."""
    return _has_trigger(text)

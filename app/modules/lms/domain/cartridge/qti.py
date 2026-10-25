"""QTI 1.2 (the Common Cartridge profile and Canvas' variant) to test blocks and back.

Supported on import: multiple choice, multiple response, true/false, fill-in
(short answer), essay, numerical and matching. Anything else becomes a ``free``
question with a note, so no question is lost silently. On export each question
type maps to the closest CC profile; the exact content also travels in the IHT
extension file, so a round trip into IHT loses nothing.
"""

import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final
from xml.sax.saxutils import escape, quoteattr

from app.modules.lms.domain.cartridge.xml_utils import (
    child,
    children,
    descendants,
    local,
    parse_xml,
    text_of,
)

TextConverter = Callable[[str], str]  # HTML (or plain) material -> markdown

_PROFILE_ALIASES: Final = {
    "cc.multiple_choice.v0p1": "single",
    "multiple_choice_question": "single",
    "cc.true_false.v0p1": "true_false",
    "true_false_question": "true_false",
    "cc.multiple_response.v0p1": "multiple",
    "multiple_answers_question": "multiple",
    "cc.fib.v0p1": "text",
    "short_answer_question": "text",
    "fill_in_multiple_blanks_question": "text",
    "cc.essay.v0p1": "free",
    "essay_question": "free",
    "cc.pattern_match.v0p1": "text",
    "numerical_question": "number",
    "matching_question": "matching",
}


@dataclass(slots=True)
class ParsedQuiz:
    """A test block (as a dict for ``StepContent``) and notes for the report."""

    title: str
    block: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def parse_qti(data: bytes, *, path: str, convert: TextConverter) -> ParsedQuiz:
    """Parse a QTI document into a test block.

    Raises:
        CartridgeInvalidError: The document is not XML.
    """
    root = parse_xml(data, path=path)
    assessment = root if local(root.tag) == "assessment" else child(root, "assessment")
    scope = assessment if assessment is not None else root
    title = (assessment.get("title", "") if assessment is not None else "").strip()
    notes: list[str] = []
    questions = []
    for item in descendants(scope, "item"):
        question = _question(item, convert, notes)
        if question is not None:
            questions.append(question)
    config: dict[str, Any] = {}
    meta = _metadata(assessment) if assessment is not None else {}
    attempts = meta.get("cc_maxattempts", "")
    if attempts.isdigit() and int(attempts) > 0:
        config["max_attempts"] = int(attempts)
    limit = meta.get("qmd_timelimit", "")
    if limit.isdigit() and int(limit) > 0:
        config["time_limit_sec"] = int(limit) * 60
    return ParsedQuiz(
        title=title,
        block={"type": "test", "config": config, "questions": questions},
        notes=notes,
    )


def _metadata(element: ET.Element) -> dict[str, str]:
    found: dict[str, str] = {}
    for meta in descendants(element, "qtimetadatafield"):
        label = text_of(child(meta, "fieldlabel"))
        if label and label not in found:
            found[label] = text_of(child(meta, "fieldentry"))
    return found


def _material(element: ET.Element | None, convert: TextConverter) -> str:
    if element is None:
        return ""
    parts: list[str] = []
    for mat in descendants(element, "mattext"):
        raw = "".join(mat.itertext())
        kind = mat.get("texttype", "text/plain").lower()
        parts.append(convert(raw) if "html" in kind or "<" in raw else raw.strip())
    return "\n\n".join(p for p in parts if p)


def _question(  # noqa: C901 - one branch per question type
    item: ET.Element, convert: TextConverter, notes: list[str]
) -> dict[str, Any] | None:
    meta = _metadata(item)
    profile = meta.get("cc_profile") or meta.get("question_type") or ""
    kind = _PROFILE_ALIASES.get(profile, "")
    presentation = child(item, "presentation")
    if presentation is None:
        return None
    prompt = _prompt(presentation, convert) or item.get("title", "").strip()
    choice = next(descendants(presentation, "response_lid"), None)
    labels = _labels(choice, convert) if choice is not None else []
    correct = _correct_idents(item)
    if not kind:
        if choice is not None:
            many = choice.get("rcardinality", "Single").lower() == "multiple"
            kind = "multiple" if many else "single"
        elif next(descendants(presentation, "response_str"), None) is not None:
            kind = "text" if correct else "free"
        elif next(descendants(presentation, "response_num"), None) is not None:
            kind = "number"
        else:
            kind = "free"
    points = _points(meta)
    base: dict[str, Any] = {"prompt": prompt or "?", "points": points}
    explanation = _feedback(item, convert)
    if explanation:
        base["explanation"] = explanation
    if kind in {"single", "true_false", "multiple"} and labels:
        options = [
            {"text": text or ident, "correct": ident in correct}
            for ident, text in labels
        ]
        if not any(o["correct"] for o in options):
            notes.append(f"no correct answer: {prompt[:80]}")
        typ = "multiple" if kind == "multiple" else "single"
        return {**base, "type": typ, "options": options}
    if kind == "text":
        accepted = sorted({c for c in correct if c}) or []
        if not accepted:
            return {**base, "type": "free"}
        return {**base, "type": "text", "answer": {"accepted": accepted}}
    if kind == "number":
        value = _number(item)
        if value is None:
            return {**base, "type": "free"}
        return {
            **base,
            "type": "number",
            "answer": {"value": value[0], "tolerance": value[1]},
        }
    if kind == "matching":
        pairs = _pairs(item, presentation, convert)
        if pairs:
            return {**base, "type": "matching", "pairs": pairs}
    if kind != "free":
        notes.append(f"question type {profile or kind} kept as free answer")
    return {**base, "type": "free"}


def _prompt(presentation: ET.Element, convert: TextConverter) -> str:
    parts: list[str] = []
    for node in presentation:
        name = local(node.tag)
        if name in {"material", "flow"}:
            if name == "flow":
                mats = list(children(node, "material"))
                parts.extend(_material(m, convert) for m in mats)
            else:
                parts.append(_material(node, convert))
    return "\n\n".join(p for p in parts if p).strip()


def _labels(choice: ET.Element, convert: TextConverter) -> list[tuple[str, str]]:
    return [
        (label.get("ident", ""), _material(label, convert))
        for label in descendants(choice, "response_label")
    ]


def _correct_idents(item: ET.Element) -> set[str]:
    found: set[str] = set()
    for condition in descendants(item, "respcondition"):
        setvar = next(descendants(condition, "setvar"), None)
        try:
            score = float(text_of(setvar) or "0") if setvar is not None else 0.0
        except ValueError:
            score = 0.0
        if score <= 0 and (setvar is None or setvar.get("action") != "Set"):
            continue
        if score <= 0:
            continue
        var = child(condition, "conditionvar")
        if var is not None:
            _collect_positive(var, found)
    return found


def _collect_positive(node: ET.Element, found: set[str]) -> None:
    for sub in node:
        name = local(sub.tag)
        if name == "not":
            continue
        if name == "varequal":
            value = text_of(sub)
            if value:
                found.add(value)
        else:
            _collect_positive(sub, found)


def _number(item: ET.Element) -> tuple[float, float] | None:
    for condition in descendants(item, "respcondition"):
        exact = next(descendants(condition, "varequal"), None)
        low = next(descendants(condition, "vargte"), None)
        high = next(descendants(condition, "varlte"), None)
        try:
            if exact is not None:
                return float(text_of(exact)), 0.0
            if low is not None and high is not None:
                a, b = float(text_of(low)), float(text_of(high))
                return (a + b) / 2, abs(b - a) / 2
        except ValueError:
            continue
    return None


def _pairs(
    item: ET.Element, presentation: ET.Element, convert: TextConverter
) -> list[dict[str, str]]:
    answers: dict[str, str] = {}
    for condition in descendants(item, "respcondition"):
        for var in descendants(condition, "varequal"):
            answers[var.get("respident", "")] = text_of(var)
    pairs = []
    for lid in descendants(presentation, "response_lid"):
        left = _material(child(lid, "material"), convert)
        labels = dict(_labels(lid, convert))
        right = labels.get(answers.get(lid.get("ident", ""), ""), "")
        if left and right:
            pairs.append({"left": left, "right": right})
    return pairs


def _points(meta: dict[str, str]) -> float:
    try:
        raw = meta.get("points_possible") or meta.get("cc_weighting") or "1"
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0


def _feedback(item: ET.Element, convert: TextConverter) -> str:
    for feedback in descendants(item, "itemfeedback"):
        if feedback.get("ident", "") in {"general_fb", "correct_fb"}:
            return _material(feedback, convert)
    return ""


# - - - Writing QTI - - -

_EXPORT_PROFILE: Final = {
    "single": "cc.multiple_choice.v0p1",
    "multiple": "cc.multiple_response.v0p1",
    "text": "cc.fib.v0p1",
}
_NS: Final = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"


def _mat(html_text: str) -> str:
    return f'<material><mattext texttype="text/html">{escape(html_text)}</mattext></material>'  # noqa: E501


def _field(label: str, entry: str) -> str:
    return (
        f"<qtimetadatafield><fieldlabel>{escape(label)}</fieldlabel>"
        f"<fieldentry>{escape(entry)}</fieldentry></qtimetadatafield>"
    )


def write_qti(
    identifier: str,
    title: str,
    block: dict[str, Any],
    render: TextConverter,
) -> tuple[str, int]:
    """Return a CC 1.3 QTI document and how many questions changed type.

    ``render`` turns question markdown into HTML.
    """
    config = block.get("config") or {}
    meta = [
        _field("cc_profile", "cc.exam.v0p1"),
        _field("qmd_assessmenttype", "Examination"),
    ]
    if config.get("max_attempts"):
        meta.append(_field("cc_maxattempts", str(config["max_attempts"])))
    if config.get("time_limit_sec"):
        minutes = max(1, int(config["time_limit_sec"]) // 60)
        meta.append(_field("qmd_timelimit", str(minutes)))
    items: list[str] = []
    changed = 0
    for number, question in enumerate(block.get("questions") or [], start=1):
        xml, exact = _item(f"{identifier}_q{number}", question, render)
        items.append(xml)
        changed += 0 if exact else 1
    body = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<questestinterop xmlns="{_NS}">'
        f"<assessment ident={quoteattr(identifier)} title={quoteattr(title)}>"
        f"<qtimetadata>{''.join(meta)}</qtimetadata>"
        f'<section ident="root_section">{"".join(items)}</section>'
        "</assessment></questestinterop>\n"
    )
    return body, changed


def _item(
    ident: str, question: dict[str, Any], render: TextConverter
) -> tuple[str, bool]:
    kind = question.get("type", "free")
    prompt = render(str(question.get("prompt", "")))
    points = question.get("points", 1.0)
    options = question.get("options") or []
    answer = question.get("answer") or {}
    exact = True
    if kind in {"single", "multiple"} and options:
        profile = _EXPORT_PROFILE[kind]
        if kind == "single" and _is_true_false(options):
            profile = "cc.true_false.v0p1"
        card = "Multiple" if kind == "multiple" else "Single"
        labels = "".join(
            f'<response_label ident="{ident}_o{n}">{_mat(render(str(o.get("text", ""))))}</response_label>'  # noqa: E501
            for n, o in enumerate(options, start=1)
        )
        response = (
            f'<response_lid ident="response1" rcardinality="{card}">'
            f"<render_choice>{labels}</render_choice></response_lid>"
        )
        correct = [
            f"{ident}_o{n}" for n, o in enumerate(options, start=1) if o.get("correct")
        ]
        wrong = [
            f"{ident}_o{n}"
            for n, o in enumerate(options, start=1)
            if not o.get("correct")
        ]
        if kind == "multiple":
            conds = "".join(
                f'<varequal respident="response1">{c}</varequal>' for c in correct
            ) + "".join(
                f'<not><varequal respident="response1">{w}</varequal></not>'
                for w in wrong
            )
            condition = f"<and>{conds}</and>"
        else:
            condition = "".join(
                f'<varequal respident="response1">{c}</varequal>' for c in correct[:1]
            )
    elif kind == "text" and answer.get("accepted"):
        profile = "cc.fib.v0p1"
        response = '<response_str ident="response1" rcardinality="Single"><render_fib><response_label ident="answer1"/></render_fib></response_str>'  # noqa: E501
        condition = "".join(
            f'<varequal respident="response1" case="No">{escape(str(a))}</varequal>'
            for a in answer["accepted"]
        )
        if len(answer["accepted"]) > 1:
            condition = f"<or>{condition}</or>"
    elif kind == "number" and answer.get("value") is not None:
        profile = "cc.fib.v0p1"
        exact = False
        response = '<response_str ident="response1" rcardinality="Single"><render_fib><response_label ident="answer1"/></render_fib></response_str>'  # noqa: E501
        condition = (
            f'<varequal respident="response1">{_num(answer["value"])}</varequal>'
        )
    else:
        profile = "cc.essay.v0p1"
        exact = kind == "free"
        response = '<response_str ident="response1" rcardinality="Single"><render_fib><response_label ident="answer1" rshuffle="No"/></render_fib></response_str>'  # noqa: E501
        condition = ""
    processing = (
        '<resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>'  # noqa: E501
        + (
            f'<respcondition continue="No"><conditionvar>{condition}</conditionvar>'
            '<setvar action="Set" varname="SCORE">100</setvar></respcondition>'
            if condition
            else ""
        )
        + "</resprocessing>"
    )
    explanation = question.get("explanation")
    feedback = (
        f'<itemfeedback ident="general_fb"><flow_mat>{_mat(render(str(explanation)))}</flow_mat></itemfeedback>'  # noqa: E501
        if explanation
        else ""
    )
    meta = _field("cc_profile", profile) + _field("cc_weighting", _num(points))
    xml = (
        f'<item ident="{ident}" title="Question">'
        f"<itemmetadata><qtimetadata>{meta}</qtimetadata></itemmetadata>"
        f"<presentation>{_mat(prompt)}{response}</presentation>"
        f"{processing}{feedback}</item>"
    )
    return xml, exact


def _is_true_false(options: list[dict[str, Any]]) -> bool:
    texts = sorted(str(o.get("text", "")).strip().casefold() for o in options)
    return texts == ["false", "true"]


def _num(value: Any) -> str:  # noqa: ANN401 - JSON number
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)

"""Markdown and JSON exports of the Studio outputs without an Office format."""

import json
from typing import Any, Final

from app.modules.notebooks.domain.enums import ArtifactKind

TEXT_KINDS: Final = (
    ArtifactKind.MIND_MAP,
    ArtifactKind.QUIZ,
    ArtifactKind.FLASHCARDS,
    ArtifactKind.INFOGRAPHIC,
    ArtifactKind.EXERCISE,
)


def _mind_map(title: str, content: dict[str, Any]) -> list[str]:
    nodes = [n for n in content.get("nodes") or [] if isinstance(n, dict)]
    children: dict[str | None, list[dict[str, Any]]] = {}
    for node in nodes:
        children.setdefault(node.get("parent_id"), []).append(node)
    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int, seen: frozenset[str]) -> None:
        node_id = str(node.get("id"))
        note = f" - {node['note']}" if node.get("note") else ""
        lines.append(f"{'  ' * depth}- {node.get('label', '')}{note}")
        if node_id in seen:
            return
        for child in children.get(node_id, []):
            walk(child, depth + 1, seen | {node_id})

    for root in children.get(None, []):
        walk(root, 0, frozenset())
    return lines


def _quiz(content: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for index, question in enumerate(content.get("questions") or [], start=1):
        correct = set(question.get("correct") or [])
        lines.append(f"{index}. {question.get('prompt', '')}")
        for option in question.get("options") or []:
            mark = "x" if option.get("id") in correct else " "
            lines.append(f"   - [{mark}] {option.get('text', '')}")
        if question.get("explanation"):
            lines.append(f"   {question['explanation']}")
        lines.append("")
    return lines


def _flashcards(content: dict[str, Any]) -> list[str]:
    lines = ["| Front | Back |", "| --- | --- |"]
    for card in content.get("cards") or []:
        front = str(card.get("front", "")).replace("|", "\\|")
        back = str(card.get("back", "")).replace("|", "\\|")
        lines.append(f"| {front} | {back} |")
    return lines


def _infographic(content: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if content.get("subtitle"):
        lines += [str(content["subtitle"]), ""]
    for block in content.get("blocks") or []:
        if block.get("title"):
            lines += [f"## {block['title']}", ""]
        for item in block.get("items") or []:
            head, body = item.get("head"), item.get("body")
            lines.append(
                f"- **{head}**: {body}" if head and body else f"- {head or body or ''}"
            )
        for column in block.get("columns") or []:
            lines.append(f"- **{column.get('title', '')}**")
            lines += [f"  - {point}" for point in column.get("points") or []]
        lines.append("")
    if content.get("footer"):
        lines.append(str(content["footer"]))
    return lines


def _answer_line(question: dict[str, Any]) -> str:
    kind = question.get("type")
    if kind == "matching":
        pairs = ", ".join(
            f"{i.get('text', '')} → {i.get('answer', '')}"
            for i in question.get("items") or []
        )
        return f"Answer: {pairs}"
    if kind in ("gap_fill", "short_answer"):
        return f"Answer: {' / '.join(question.get('accepted') or [])}"
    if kind == "free_response":
        return ""
    return f"Answer: {', '.join(question.get('correct') or [])}"


def _exercise_question(question: dict[str, Any]) -> list[str]:
    lines = [f"**{question.get('number', '')}.** {question.get('prompt', '')}"]
    if question.get("word_limit"):
        lines.append(f"   (no more than {question['word_limit']} words)")
    for option in question.get("options") or []:
        lines.append(f"   - {option.get('id', '')}. {option.get('text', '')}")
    for item in question.get("items") or []:
        lines.append(f"   - {item.get('text', '')} ____")
    if question.get("type") == "free_response":
        lines.append(
            f"   ({question.get('min_words', 0)}+ words, "
            f"{question.get('time_minutes', 0)} min)"
        )
        for criterion in question.get("criteria") or []:
            lines.append(f"   - {criterion.get('name', '')}")
    lines.append("")
    return lines


def _exercise(content: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if content.get("instructions"):
        lines += [str(content["instructions"]), ""]
    keys: list[str] = []
    for section in content.get("sections") or []:
        if section.get("title"):
            lines += [f"## {section['title']}", ""]
        lines += [str(section.get("stimulus") or ""), ""]
        for question in section.get("questions") or []:
            lines += _exercise_question(question)
            answer = _answer_line(question)
            if answer:
                keys.append(f"{question.get('number', '')}. {answer[8:]}")
    if keys:
        lines += ["## Answer key", "", *[f"- {key}" for key in keys]]
    return lines


def to_markdown(kind: ArtifactKind, title: str, content: dict[str, Any]) -> str:
    """Render the output as a Markdown document."""
    heading = str(content.get("title") or title)
    if kind is ArtifactKind.MIND_MAP:
        body = _mind_map(heading, content)
    elif kind is ArtifactKind.QUIZ:
        body = _quiz(content)
    elif kind is ArtifactKind.FLASHCARDS:
        body = _flashcards(content)
    elif kind is ArtifactKind.INFOGRAPHIC:
        body = _infographic(content)
    elif kind is ArtifactKind.EXERCISE:
        body = _exercise(content)
    else:
        body = [str(content.get("markdown") or "")]
    return "\n".join([f"# {heading}", "", *body]).rstrip() + "\n"


def to_json(title: str, content: dict[str, Any]) -> str:
    """Render the output as pretty JSON with its title."""
    return json.dumps({"title": title, **content}, ensure_ascii=False, indent=2)

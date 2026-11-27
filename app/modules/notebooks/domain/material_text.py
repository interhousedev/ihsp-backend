"""Text renderings of teaching materials and citations into media."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.shared.contracts.material_sink import TimedText
from app.shared.contracts.teacher_ai import CheckWorkResult, QuestionItem


def _stamp(ms: int) -> str:
    seconds = ms // 1000
    return f"[{seconds // 60:02d}:{seconds % 60:02d}]"


def media_text(title: str, segments: Sequence[TimedText]) -> str:
    """The script, one line per segment: `[mm:ss] text`."""
    lines = [f"# {title}", ""]
    lines.extend(f"{_stamp(s.start_ms)} {s.text}" for s in segments)
    return "\n".join(lines)


def questions_text(topic: str, questions: Sequence[QuestionItem]) -> str:
    """Questions with options, answers and explanations."""
    out = [f"# {topic}", ""]
    for number, q in enumerate(questions, 1):
        out.append(f"{number}. {q.question}")
        out.extend(f"   - {option}" for option in q.options)
        out.append(f"   Answer: {q.answer}")
        if q.explanation:
            out.append(f"   Explanation: {q.explanation}")
        out.append("")
    return "\n".join(out).rstrip()


def work_check_text(result: CheckWorkResult) -> str:
    """Every field of a work check."""
    score = "" if result.score is None else f"{result.score:g}"
    if result.max_score is not None:
        score = f"{score}/{result.max_score:g}"
    out = [result.summary]
    if score:
        out.append(f"Score: {score}")
    for head, items in (
        ("Strengths", result.strengths),
        ("Issues", result.issues),
        ("Suggestions", result.suggestions),
    ):
        if items:
            out.append(f"{head}:")
            out.extend(f"- {item}" for item in items)
    return "\n".join(out)


@dataclass(frozen=True, slots=True)
class MediaCitation:
    """A moment of a media file a cited passage was said at."""

    media_file_id: UUID
    start_ms: int


def citation_for(
    source_ref: Mapping[str, Any], body_md: str, passage: str
) -> MediaCitation | None:
    """Map the `[mm:ss]` line holding the passage to its media file and moment."""
    file_id = source_ref.get("media_file_id")
    segments = source_ref.get("segments") or []
    needle = passage.strip()
    if file_id is None or not needle:
        return None
    index = 0
    for line in body_md.splitlines():
        if not line.startswith("["):
            continue
        if index >= len(segments):
            return None
        if needle in line:
            return MediaCitation(UUID(str(file_id)), int(segments[index]["start_ms"]))
        index += 1
    return None

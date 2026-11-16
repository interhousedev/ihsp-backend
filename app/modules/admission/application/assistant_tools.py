"""Tools of the admission assistant: reads of the caller's own data and UI cards.

Every tool works for the one student the box was made for; arguments that name
another student are never read. The propose tools change nothing: they only
return a card the student may click.
"""

import datetime as dt
from typing import Any, Final
from uuid import UUID

from app.modules.admission.domain.assistant import Action, Citation, Screen
from app.modules.admission.domain.tasks import is_internal_path
from app.modules.admission.ports.assistant import AssistantData
from app.modules.admission.ports.student_search import StudentDataSearch
from app.shared.ai.injection import neutralize

_LABEL_MAX: Final = 80
_TASK_TITLE_MAX: Final = 200
_TASK_TEXT_MAX: Final = 1000
_QUERY_MAX: Final = 300
_HITS: Final = 8


def _fn(
    name: str,
    description: str,
    props: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            },
        },
    }


TOOLS: Final[list[dict[str, Any]]] = [
    _fn(
        "search_student_data",
        "Search the student's own records (profile, activities, essays, tasks, "
        "test scores, documents, list, courses) by meaning. Cite what you use.",
        {"query": {"type": "string", "description": "What to look for."}},
        ["query"],
    ),
    _fn("get_profile", "The student's profile stage and filled answers."),
    _fn("list_tasks", "The student's tasks with status and deadline."),
    _fn("list_items", "The student's activities and honors."),
    _fn("list_test_scores", "The student's entered test scores and sittings."),
    _fn("upcoming_deadlines", "Milestones of the student's university list."),
    _fn("list_universities", "The universities on the student's list."),
    _fn("list_courses_and_grades", "The student's courses with grades."),
    _fn("get_screen", "The text of the page the student is looking at now."),
    _fn(
        "propose_open",
        "Offer a button that opens a page of the app. Nothing is changed.",
        {
            "label": {"type": "string"},
            "url_path": {"type": "string", "description": "An app path, e.g. /essays/"},
        },
        ["label", "url_path"],
    ),
    _fn(
        "propose_task",
        "Offer a button that lets the student add a task. Nothing is created "
        "until they click it.",
        {
            "label": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "due_on": {"type": "string", "description": "YYYY-MM-DD or empty"},
        },
        ["label", "title"],
    ),
]

_DATA_TOOLS: Final = {
    "list_tasks": "tasks",
    "list_items": "items",
    "list_test_scores": "test_scores",
    "upcoming_deadlines": "deadlines",
    "list_universities": "universities",
    "list_courses_and_grades": "courses",
}


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _safe_path(value: Any) -> str | None:
    path = str(value or "").strip()
    return path if len(path) <= 300 and is_internal_path(path) else None


class ToolBox:
    """Runs the tools of one turn for one student; collects citations and cards."""

    def __init__(
        self,
        student_id: UUID,
        data: AssistantData,
        search: StudentDataSearch,
        screen: Screen | None,
    ) -> None:
        """Bind the box to the caller's id and the screen they sent."""
        self._student = student_id
        self._data = data
        self._search = search
        self._screen = screen
        self.citations: list[Citation] = []
        self.actions: list[Action] = []

    async def run(self, name: str, args: dict[str, Any]) -> Any:
        """Run a tool; the result is neutralized JSON. Unknown names are refused."""
        try:
            result = await self._dispatch(name, args)
        except (TypeError, ValueError):
            result = {"error": "bad arguments"}
        return neutralize(result)

    async def _dispatch(self, name: str, args: dict[str, Any]) -> Any:
        if name == "search_student_data":
            return await self._find(_text(args.get("query"), _QUERY_MAX))
        if name == "get_profile":
            return await self._data.profile(self._student)
        if name in _DATA_TOOLS:
            return await getattr(self._data, _DATA_TOOLS[name])(self._student)
        if name == "get_screen":
            s = self._screen
            if s is None:
                return {"screen": None}
            return {"path": s.path, "title": s.title, "summary": s.summary}
        if name == "propose_open":
            return self._open(args)
        if name == "propose_task":
            return self._task(args)
        return {"error": "unknown tool"}

    async def _find(self, query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        hits = await self._search.search(self._student, query, limit=_HITS)
        seen = {(c.source, c.url_path) for c in self.citations}
        for h in hits:
            if (h.source, h.url_path) not in seen:
                seen.add((h.source, h.url_path))
                self.citations.append(Citation(h.source, h.title, h.url_path))
        return [
            {
                "source": h.source,
                "title": h.title,
                "snippet": h.snippet,
                "url_path": h.url_path,
            }
            for h in hits
        ]

    def _open(self, args: dict[str, Any]) -> dict[str, Any]:
        path, label = _safe_path(args.get("url_path")), _text(
            args.get("label"), _LABEL_MAX
        )
        if path is None or not label:
            return {"error": "bad arguments"}
        self.actions.append(Action("open", label, url_path=path))
        return {"ok": True, "shown": label}

    def _task(self, args: dict[str, Any]) -> dict[str, Any]:
        title = _text(args.get("title"), _TASK_TITLE_MAX)
        label = _text(args.get("label"), _LABEL_MAX) or title
        if not title:
            return {"error": "bad arguments"}
        raw = str(args.get("due_on") or "").strip()
        due: str | None = None
        if raw:
            due = dt.date.fromisoformat(raw).isoformat()
        task = {
            "title": title,
            "description": _text(args.get("description"), _TASK_TEXT_MAX),
            "due_on": due,
        }
        self.actions.append(Action("propose_task", label, task=task))
        return {"ok": True, "shown": label}

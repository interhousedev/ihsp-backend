"""The teacher's work-off choice for a lesson, kept in the FSM data (WO-5)."""

from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.services import BotServices
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext

FSM_KEY = "work_offs"
TEXT_MAX_CHARS = 1000


@dataclass(frozen=True, slots=True)
class TemplateItem:
    """One of the teacher's work-off templates."""

    id: str
    text: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class WorkOffChoice:
    """What the absent students of the lesson get: a template and/or a text."""

    template: TemplateItem | None
    text: str | None
    templates: tuple[TemplateItem, ...]

    @property
    def chosen(self) -> bool:
        """True when there is anything to give."""
        return self.template is not None or bool(self.text)

    def payload(self) -> dict[str, Any]:
        """Return the ``common_work_off`` argument of ``submit_attendance``."""
        return {
            "template_id": None if self.template is None else self.template.id,
            "text": self.text,
            "due_date": None,
        }

    def summary(self, i18n: I18nContext, limit: int = 120) -> str:
        """Return a plain one-line description of the choice."""
        parts = [p.text for p in (self.template,) if p is not None]
        if self.text:
            parts.append(self.text)
        if not parts:
            return i18n("bot-prompt-work-off-none")
        joined = " + ".join(part.replace("\n", " ") for part in parts)
        return joined if len(joined) <= limit else joined[: limit - 1] + "…"


def _items(raw: list[dict[str, Any]]) -> tuple[TemplateItem, ...]:
    return tuple(
        TemplateItem(str(r["id"]), str(r["text"]), bool(r.get("is_default", False)))
        for r in raw
    )


async def load_choice(
    fsm: FSMContext, services: BotServices, teacher_id: Any, lesson: str
) -> WorkOffChoice:
    """Read the choice for the lesson; the default template until the teacher picks."""
    templates = _items(await services.classwork_queries.work_off_templates(teacher_id))
    entry = (await fsm.get_data()).get(FSM_KEY, {}).get(lesson)
    if entry is None:
        default = next((t for t in templates if t.is_default), None)
        return WorkOffChoice(default, None, templates)
    chosen = next((t for t in templates if t.id == entry.get("template")), None)
    return WorkOffChoice(chosen, entry.get("text") or None, templates)


async def store_choice(
    fsm: FSMContext, lesson: str, *, template: TemplateItem | None, text: str | None
) -> None:
    """Remember the explicit choice (even "nothing") for the lesson."""
    entries = dict((await fsm.get_data()).get(FSM_KEY, {}))
    entries[lesson] = {
        "template": None if template is None else template.id,
        "text": text,
    }
    await fsm.update_data({FSM_KEY: entries})


async def forget_choice(fsm: FSMContext, lesson: str) -> None:
    """Drop the choice after the attendance is saved."""
    entries = dict((await fsm.get_data()).get(FSM_KEY, {}))
    if entries.pop(lesson, None) is not None:
        await fsm.update_data({FSM_KEY: entries})

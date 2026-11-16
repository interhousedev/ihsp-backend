"""Versions of the item prompts and the one place that fills them.

The text of a prompt comes from the `PromptSource` (the prompt registry: the active
version, else the built-in text); `render_prompt` only fills its placeholders.
"""

from typing import Final

from app.modules.admission.ports.ai import PromptSource
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand

PROMPT_VERSION: Final = "items-2026-11-1"
SCHEMA_VERSION: Final = "items-2026-11-1"

LANGUAGES: Final[dict[str, str]] = {
    "uz": "Uzbek (Latin)",
    "ru": "Russian",
    "en": "English",
}


async def render_prompt(
    source: PromptSource, task: AiTask, name: str, locale: str, **values: object
) -> str:
    """Return a filled prompt of a task in the language of `locale`."""
    template = with_brand(await source.text(task, name, locale))
    language = LANGUAGES.get(locale, LANGUAGES["en"])
    return template.format(language=language, **values)

"""Subject names with a missing language are translated once (T6.2)."""

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.translate_subject import TranslateSubject
from app.modules.academic.infrastructure.schedule.subject_translation import (
    LlmSubjectTranslator,
)
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.settings import Settings
from app.shared.ai_tasks import TRANSLATE_MODEL, AiTask
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.emis import EmisSubject
from app.shared.ids import new_id
from tests.academic.schedule.env import Env

SUBJECT_ID = new_id()


class MemoryNames:
    """The name map of one subject in memory."""

    def __init__(self, names: dict[str, str]) -> None:
        """Start with the given names."""
        self.stored = dict(names)

    async def names(self, subject_id: UUID) -> dict[str, str] | None:
        """Return a copy of the names."""
        return dict(self.stored)

    async def fill_missing(
        self, subject_id: UUID, names: Mapping[str, str]
    ) -> dict[str, str]:
        """Fill only the empty languages."""
        written = {k: v for k, v in names.items() if not self.stored.get(k)}
        self.stored.update(written)
        return written


class TitleCaseGateway(FakeLlmGateway):
    """Answers a real-looking translation instead of echoing the source."""

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """Prefix the first known name with the language code."""
        request = json.loads(kwargs["messages"][-1]["content"])
        source = next(v for v in request["known"].values() if v)
        data = {
            c: f"{c}:{source}" if c in request["missing"] else ""
            for c in ("uz", "ru", "en")
        }
        self._record(kwargs["model"], kwargs["system"], kwargs["messages"])
        return {"data": data, "text": json.dumps(data), "usage": {}}


class FailingGateway(FakeLlmGateway):
    """Every call fails."""

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """Raise a provider error."""
        raise AiProviderError(support_details="down")


def use_case(
    store: MemoryNames, gateway: FakeLlmGateway, settings: Settings
) -> TranslateSubject:
    """The use case over the memory store and a gateway."""
    return TranslateSubject(store, LlmSubjectTranslator(gateway, settings))


async def test_only_the_missing_languages_are_filled(settings: Settings) -> None:
    """One call: the known name goes in, only the empty languages come out."""
    store = MemoryNames({"uz": "", "ru": "Физика", "en": ""})
    gateway = TitleCaseGateway()

    written = await use_case(store, gateway, settings).execute(SUBJECT_ID)

    assert written == {"uz": "uz:Физика", "en": "en:Физика"}
    assert store.stored == {"uz": "uz:Физика", "ru": "Физика", "en": "en:Физика"}
    assert len(gateway.requests) == 1
    assert gateway.requests[0]["model"] == TRANSLATE_MODEL
    assert settings.ai_profile(AiTask.SUBJECT_TRANSLATE).model == TRANSLATE_MODEL


async def test_a_second_run_makes_no_call(settings: Settings) -> None:
    """A filled language is never translated again."""
    store = MemoryNames({"uz": "", "ru": "Физика", "en": "Physics"})
    gateway = TitleCaseGateway()
    case = use_case(store, gateway, settings)

    await case.execute(SUBJECT_ID)
    again = await case.execute(SUBJECT_ID)

    assert again == {}
    assert store.stored["en"] == "Physics"
    assert len(gateway.requests) == 1


async def test_a_full_name_is_not_sent_to_the_model(settings: Settings) -> None:
    """Nothing missing, nothing asked."""
    store = MemoryNames({"uz": "Fizika", "ru": "Физика", "en": "Physics"})
    gateway = TitleCaseGateway()

    assert await use_case(store, gateway, settings).execute(SUBJECT_ID) == {}
    assert len(gateway.requests) == 0


async def test_a_failure_leaves_the_names_unchanged(settings: Settings) -> None:
    """A provider error is logged and nothing is written."""
    store = MemoryNames({"uz": "Fizika", "ru": "", "en": ""})

    written = await use_case(store, FailingGateway(), settings).execute(SUBJECT_ID)

    assert written == {}
    assert store.stored == {"uz": "Fizika", "ru": "", "en": ""}


async def test_the_fake_model_returns_the_source_name(settings: Settings) -> None:
    """Fake mode: the missing languages get the name EMIS gave."""
    store = MemoryNames({"uz": "", "ru": "", "en": "Chemistry"})

    await use_case(store, FakeLlmGateway(), settings).execute(SUBJECT_ID)

    assert store.stored == {"uz": "Chemistry", "ru": "Chemistry", "en": "Chemistry"}


async def test_the_emis_subject_sync_kicks_a_translation_only_for_gaps(
    env: Env,
) -> None:
    """The sync starts one background task per subject with a missing language."""
    group = await env.group()
    emis = [
        EmisSubject(emis_subject_id=1, name_uz="", name_ru="Физика", name_en=""),
        EmisSubject(
            emis_subject_id=2, name_uz="Kimyo", name_ru="Химия", name_en="Chemistry"
        ),
    ]

    await env.services.enrollment.sync_subjects(group_id=group.id, subjects=emis)

    calls = [c for c in env.kicker.calls if c[0] == "academic.translate_subject"]
    assert len(calls) == 1
    async with env.uow_factory() as uow:
        subject = await uow.subjects.get_by_emis_id(1)
    assert subject is not None
    assert calls[0][1] == {"subject_id": str(subject.id)}

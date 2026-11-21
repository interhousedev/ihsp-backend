"""Short human names of prompt groups, generated once and stored.

A group is named by the digest of its member prompts, so a label is reused by every
student and regenerated only when the membership or a prompt text changes. The
prompts are public catalog text; no student data goes to the model. When the model
is unavailable the caller falls back to the first words of the first prompt and
nothing is stored, so the next call tries again.
"""

import logging
from collections.abc import Sequence
from typing import Any, Final

from app.modules.admission.application.review_checks import nfc
from app.modules.admission.application.words import delimit, plain
from app.modules.admission.domain.essay_flow import (
    LABEL_MAX,
    GroupLabel,
    PromptGroup,
    members_hash,
)
from app.modules.admission.infrastructure.ai.prompts import essay_flow as flow
from app.modules.admission.ports.ai import PromptSource, StructuredAi
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.ai_tasks import AiTask
from app.shared.brand import with_brand

_log = logging.getLogger(__name__)
_BATCH: Final = 20
_PROMPTS_SHOWN: Final = 6
_PROMPT_CHARS: Final = 300
_TOKENS: Final = 2000


def _clean(value: Any) -> str:
    return nfc(plain(str(value or ""))).strip().strip("\"'«»")[:LABEL_MAX]


def parse_labels(
    data: dict[str, Any], asked: dict[str, str], model: str
) -> list[GroupLabel]:
    """The usable labels of a model reply; `asked` maps group key to members hash."""
    out: dict[str, GroupLabel] = {}
    for raw in data.get("labels") or []:
        if not isinstance(raw, dict):
            continue
        digest = asked.get(str(raw.get("key")))
        if digest is None or digest in out:
            continue
        en, ru, uz = (_clean(raw.get(k)) for k in ("en", "ru", "uz"))
        best = en or ru or uz
        if best:
            out[digest] = GroupLabel(
                digest, ru or best, en or best, uz or ru or best, model
            )
    return list(out.values())


class GroupLabeler:
    """Labels of prompt groups: stored ones, and one model call for the missing."""

    def __init__(
        self, uow_factory: UowFactory, ai: StructuredAi, prompts: PromptSource
    ) -> None:
        """Keep the unit of work factory, the model and the prompt source."""
        self._uow = uow_factory
        self._ai = ai
        self._prompts = prompts

    async def labels(self, groups: Sequence[PromptGroup]) -> dict[str, GroupLabel]:
        """Labels by group key; a group the model could not name is missing."""
        digests = {g.key: members_hash(g.prompts) for g in groups}
        async with self._uow() as uow:
            have = await uow.group_labels.get_many(list(set(digests.values())))
        missing = [g for g in groups if digests[g.key] not in have]
        for start in range(0, len(missing), _BATCH):
            made = await self._generate(missing[start : start + _BATCH], digests)
            if not made:
                break
            async with self._uow() as uow:
                await uow.group_labels.put_many(made)
                await uow.commit()
            have.update({g.members_hash: g for g in made})
        return {k: have[d] for k, d in digests.items() if d in have}

    async def _generate(
        self, groups: Sequence[PromptGroup], digests: dict[str, str]
    ) -> list[GroupLabel]:
        lines: list[str] = []
        for g in groups:
            lines.append(f"Group {g.key}:")
            lines.extend(
                f"- {p.prompt[:_PROMPT_CHARS]}" for p in g.prompts[:_PROMPTS_SHOWN]
            )
        task = AiTask.ADMIT_PROMPT_GROUP_LABEL
        name, schema = flow.SCHEMAS["group_label"]
        try:
            data, model = await self._ai.json(
                task=task,
                system=with_brand(await self._prompts.text(task, "group_label", "en")),
                user=delimit(lines),
                schema_name=name,
                schema=schema,
                max_tokens=_TOKENS,
            )
        except Exception:  # noqa: BLE001 - a model outage must not break the map
            _log.warning("prompt group labels unavailable", exc_info=True)
            return []
        return parse_labels(data, {g.key: digests[g.key] for g in groups}, model)

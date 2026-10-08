"""Use case: the journals a teacher can open (STF-9)."""

from collections.abc import Callable
from typing import Any

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.records import JournalOption
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


def audience_key_of(keys: tuple[str, ...]) -> str:
    """The journal's ``audience_key``: the lesson's audience keys, sorted and joined."""
    return ",".join(sorted(keys))


def audience_label(option: JournalOption) -> str:
    """A short label like ``2TN2/1`` or ``2TN1/2 + 2TN2/2``."""
    parts = []
    for key in option.audience:
        group_id, subgroup = audience_keys.parse(key)
        name = option.groups.get(group_id, str(group_id))
        parts.append(name if subgroup is None else f"{name}/{subgroup}")
    return " + ".join(parts)


class JournalOptions:
    """Subject and audience pairs from the teacher's lessons in the current term."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people

    async def execute(self, actor: Actor) -> list[dict[str, Any]]:
        """Return ``{"subject": SubjectRef, "audience_key", "label"}`` items."""
        today = local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            term = await uow.results.current_term(today)
            if term is None:
                return []
            options = await uow.journal.options(
                actor.user_id, term.starts_on, term.ends_on
            )
        items: list[dict[str, Any]] = []
        for option in options:
            name = localized(option.subject_names, locale)
            items.append(
                {
                    "subject": {
                        "id": str(option.subject_id),
                        "name": name,
                        "short_name": option.subject_short or name,
                    },
                    "audience_key": audience_key_of(option.audience),
                    "label": audience_label(option),
                }
            )
        items.sort(key=lambda item: (item["subject"]["name"], item["label"]))
        return items

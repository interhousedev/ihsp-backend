"""Topic labels of sources: the labels, their links and the auto labeling (G12/G13)."""

import asyncio
from dataclasses import dataclass

from app.modules.notebooks.application.create_label import CreateLabel
from app.modules.notebooks.application.delete_label import DeleteLabel
from app.modules.notebooks.application.label_sources import LabelSources
from app.modules.notebooks.application.light_json import LightJson, Sleep
from app.modules.notebooks.application.list_labels import ListLabels
from app.modules.notebooks.application.set_source_labels import SetSourceLabels
from app.modules.notebooks.application.start_labeling import StartLabeling
from app.modules.notebooks.application.update_label import UpdateLabel
from app.modules.notebooks.wiring_core import NotebooksCore


@dataclass(frozen=True, slots=True)
class LabelsServices:
    """Use cases of the topic labels and the labeling job (attribute = file name)."""

    list_labels: ListLabels
    create_label: CreateLabel
    update_label: UpdateLabel
    delete_label: DeleteLabel
    set_source_labels: SetSourceLabels
    start_labeling: StartLabeling
    label_sources: LabelSources


def build_labels(core: NotebooksCore, *, sleep: Sleep = asyncio.sleep) -> LabelsServices:
    """Build the label use cases; `sleep` is the pause between model retries."""
    deps = core.deps
    return LabelsServices(
        list_labels=ListLabels(uow_factory=core.uow_factory, clock=deps.clock),
        create_label=CreateLabel(uow_factory=core.uow_factory, clock=deps.clock),
        update_label=UpdateLabel(uow_factory=core.uow_factory),
        delete_label=DeleteLabel(uow_factory=core.uow_factory),
        set_source_labels=SetSourceLabels(uow_factory=core.uow_factory),
        start_labeling=StartLabeling(
            uow_factory=core.uow_factory, clock=deps.clock, kicker=deps.kicker
        ),
        label_sources=LabelSources(
            uow_factory=core.uow_factory,
            clock=deps.clock,
            light=LightJson(llm=core.llm, budget=core.budget, sleep=sleep),
            locale=core.locale,
        ),
    )

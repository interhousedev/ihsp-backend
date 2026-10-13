"""NB-8, NB-9: Studio outputs are checked against their sources by a small model."""

from app.modules.notebooks.application.faithfulness_check import (
    UNVERIFIED,
    VERIFICATION_KEY,
    FaithfulnessCheck,
)
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.artifacts.handler import ProcessedOutput
from app.modules.notebooks.domain.retrieval_plan import FAITHFULNESS_SCHEMA_NAME
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiProviderError
from tests.fakes.notebooks.llm import ScriptedLlm

SOURCES = '<sources>\n<source id="S1">[S1:P1] Cells are small.</source>\n</sources>'
FIRST = ProcessedOutput(
    title="Cells", content={"text": "Cells are huge."}, refs_index={}
)
SECOND = ProcessedOutput(
    title="Cells", content={"text": "Cells are small."}, refs_index={}
)


def checker(
    settings: Settings, gateway: ScriptedLlm, *, on: bool = True
) -> FaithfulnessCheck:
    """The check over a scripted gateway, switched on or off."""
    tuned = settings.model_copy(
        update={
            "notebooks": settings.notebooks.model_copy(
                update={"faithfulness_check": on}
            )
        }
    )
    return FaithfulnessCheck(NotebookLlm(gateway, tuned), tuned)


class Regenerate:
    """Counts the regenerations and returns a fixed output (or None: it failed)."""

    def __init__(self, output: ProcessedOutput | None) -> None:
        """Keep the output."""
        self.output = output
        self.calls = 0

    async def __call__(self) -> ProcessedOutput | None:
        """One regeneration."""
        self.calls += 1
        return self.output


async def test_a_faithful_output_is_kept_as_it_is(settings: Settings) -> None:
    """One cheap call; no regeneration, no mark."""
    gateway = ScriptedLlm()
    gateway.queue_json({"faithful": True, "unsupported": []}, usage={"input": 50})
    regenerate = Regenerate(SECOND)

    result = await checker(settings, gateway).ensure(FIRST, SOURCES, regenerate)

    assert result.output == FIRST
    assert regenerate.calls == 0
    assert result.usage.input == 50
    request = gateway.json_requests[0]
    assert request["schema_name"] == FAITHFULNESS_SCHEMA_NAME
    assert request["tuning"].task == AiTask.STUDIO_FAITHFULNESS.value
    assert "Cells are huge." in request["messages"][0]["content"]


async def test_an_unfaithful_output_is_regenerated_once(settings: Settings) -> None:
    """The regenerated output passes and replaces the first."""
    gateway = ScriptedLlm()
    gateway.queue_json({"faithful": False, "unsupported": ["Cells are huge."]})
    gateway.queue_json({"faithful": True, "unsupported": []})
    regenerate = Regenerate(SECOND)

    result = await checker(settings, gateway).ensure(FIRST, SOURCES, regenerate)

    assert result.output == SECOND
    assert regenerate.calls == 1
    assert gateway.calls == 2


async def test_a_second_failure_marks_the_output_unverified(settings: Settings) -> None:
    """No endless loop: after one regeneration the output is delivered, marked."""
    gateway = ScriptedLlm()
    gateway.queue_json({"faithful": False, "unsupported": ["a"]})
    gateway.queue_json({"faithful": False, "unsupported": ["b"]})
    regenerate = Regenerate(SECOND)

    result = await checker(settings, gateway).ensure(FIRST, SOURCES, regenerate)

    assert regenerate.calls == 1
    assert result.output.content[VERIFICATION_KEY] == {
        "status": UNVERIFIED,
        "unsupported": ["b"],
    }
    assert result.output.content["text"] == "Cells are small."


async def test_a_failed_regeneration_keeps_the_first_output_marked(
    settings: Settings,
) -> None:
    """The regeneration gave nothing: the first output is delivered, unverified."""
    gateway = ScriptedLlm()
    gateway.queue_json({"faithful": False, "unsupported": ["a"]})

    result = await checker(settings, gateway).ensure(FIRST, SOURCES, Regenerate(None))

    assert result.output.content["text"] == "Cells are huge."
    assert result.output.content[VERIFICATION_KEY]["status"] == UNVERIFIED


async def test_a_failing_checker_delivers_the_output_unchanged(
    settings: Settings,
) -> None:
    """The check is best effort: a provider error does not mark or block."""
    gateway = ScriptedLlm()
    gateway.queue_error(AiProviderError(support_details="HTTP 503"))
    regenerate = Regenerate(SECOND)

    result = await checker(settings, gateway).ensure(FIRST, SOURCES, regenerate)

    assert result.output == FIRST
    assert regenerate.calls == 0


async def test_switched_off_or_without_sources_nothing_is_checked(
    settings: Settings,
) -> None:
    """The default and source-less outputs make no call."""
    gateway = ScriptedLlm()

    off = await checker(settings, gateway, on=False).ensure(
        FIRST, SOURCES, Regenerate(SECOND)
    )
    empty = await checker(settings, gateway).ensure(FIRST, "", Regenerate(SECOND))

    assert off.output == FIRST
    assert empty.output == FIRST
    assert gateway.calls == 0

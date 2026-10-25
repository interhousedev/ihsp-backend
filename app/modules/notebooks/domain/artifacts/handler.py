"""The contract of one kind of Studio output (§ 3.4); see `kinds/`."""

from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.enums import ArtifactKind

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ProcessContext:
    """What `process()` needs besides the model's JSON."""

    pack: ContextPack
    language: str  # uz | ru | en
    seed: int  # stable per artifact (seeded shuffles)


@dataclass(frozen=True, slots=True)
class ProcessedOutput:
    """A validated, post-processed output ready to be stored."""

    title: str
    content: dict[str, Any]  # stored in artifacts.content (<= 512 KB)
    refs_index: dict[str, Any]  # {} for reports


class ArtifactHandler(Protocol):
    """Everything kind-specific: options, prompt, schema, validation."""

    kind: ArtifactKind
    schema_name: str  # response_format.json_schema.name, e.g. "nb_quiz"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options; raise `InvalidOptionsError`."""
        ...

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options as echoed back and stored: defaults filled, JSON-safe."""
        ...

    def report_format(self, options: BaseModel) -> str | None:
        """The `artifacts.format` value (report format) or None."""
        ...

    def max_tokens(self, options: BaseModel) -> int:
        """`max_tokens` of the model call (§ 3.4.0 table)."""
        ...

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """Context cap for this kind (150k by default, 100k for infographics)."""
        ...

    def strict_schema(self) -> dict[str, Any]:
        """The strict JSON schema sent as `response_format`."""
        ...

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The per-kind task block (English); the last user message."""
        ...

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """Title shown while generating, e.g. "Conspect: <notebook>"."""
        ...

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Validate and fix the model's JSON, resolve refs, trim and shuffle.

        Raises `OutputInvalidError(problems)` when the document is unusable; the
        engine then makes one repair call with the problems.
        """
        ...

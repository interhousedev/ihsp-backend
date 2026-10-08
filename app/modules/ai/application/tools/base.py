"""Base classes of assistant tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar
from uuid import UUID

from app.modules.ai.domain.json_schema import tool_parameters
from app.modules.ai.domain.tool_args import ToolArgs, parse_args
from app.modules.ai.domain.tool_call import PreviewData, ToolAccess
from app.modules.ai.domain.tools import ToolSpec
from app.shared.actor import Actor

# Classic generics: pydocstyle cannot parse the PEP 695 class syntax.
A = TypeVar("A", bound=ToolArgs)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Who runs a tool, in which chat, in which language."""

    actor: Actor
    chat_id: UUID
    locale: str


class _Tool(ABC, Generic[A]):
    """Shared parts of read and write tools."""

    name: str
    access: ClassVar[ToolAccess]
    description: str
    args_model: type[ToolArgs]

    def spec(self) -> ToolSpec:
        """Return the description the model sees."""
        return ToolSpec(
            name=self.name,
            access=self.access,
            description=self.description,
            parameters=tool_parameters(self.args_model),
        )

    def parse(self, raw: dict[str, Any]) -> A:
        """Validate the model's arguments (raises ToolArgumentsError)."""
        return parse_args(self.args_model, raw)  # type: ignore[return-value]

    async def validate(self, args: A, ctx: ToolContext) -> None:  # noqa: B027
        """Check that the call may run now; raise a BaseError otherwise."""

    @abstractmethod
    async def run(self, args: A, ctx: ToolContext) -> dict[str, Any]:
        """Run the tool and return a JSON-serializable result."""


class ReadTool(_Tool[A]):
    """A tool that only reads; it runs at once."""

    access: ClassVar[ToolAccess] = ToolAccess.READ


class WriteTool(_Tool[A]):
    """A tool that changes data; every call waits for the user's approval."""

    access: ClassVar[ToolAccess] = ToolAccess.WRITE

    @abstractmethod
    async def preview(self, args: A, ctx: ToolContext) -> PreviewData:
        """Build the approval card from the real arguments."""


type Tool = ReadTool[Any] | WriteTool[Any]

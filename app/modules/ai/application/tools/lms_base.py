"""Base classes of the course author tools: closed schemas and shared collaborators."""

from typing import TypeVar

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, WriteTool
from app.modules.ai.domain.json_schema import strict_tool_parameters
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tools import ToolSpec
from app.shared.i18n.core import I18nCore

A = TypeVar("A", bound=ToolArgs)


class AuthorReadTool(ReadTool[A]):
    """A read tool of the author assistant; nested objects forbid extra keys too."""

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound LMS and notebooks contracts."""
        self.bindings = bindings

    def spec(self) -> ToolSpec:
        """Return the description and the closed JSON schema the model sees."""
        return ToolSpec(
            name=self.name,
            access=self.access,
            description=self.description,
            parameters=strict_tool_parameters(self.args_model),
        )


class AuthorWriteTool(WriteTool[A]):
    """A write tool of the author assistant (approval card lines are localized)."""

    def __init__(self, bindings: LateBindings, i18n: I18nCore) -> None:
        """Store the late-bound contracts and the translations of card lines."""
        self.bindings = bindings
        self.i18n = i18n

    def spec(self) -> ToolSpec:
        """Return the description and the closed JSON schema the model sees."""
        return ToolSpec(
            name=self.name,
            access=self.access,
            description=self.description,
            parameters=strict_tool_parameters(self.args_model),
        )

"""Base class of tool argument models (strict: unknown keys are errors)."""

from typing import Any, TypeVar

from app.modules.ai.domain.errors import ToolArgumentsError

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolArgs(BaseModel):
    """Arguments of one tool; the JSON schema sent to the model comes from it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def as_json(self) -> dict[str, Any]:
        """Return the arguments as plain JSON values (aliases, no nulls)."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


T = TypeVar("T", bound=ToolArgs)


def parse_args(model: type[T], raw: dict[str, Any]) -> T:
    """Validate the model's arguments or raise ToolArgumentsError with details."""
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ToolArgumentsError(
            params={"details": problems}, support_details=problems
        ) from exc

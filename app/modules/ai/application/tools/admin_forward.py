"""Administration tools: forwarded to the AdminToolBackend (AI-6)."""

import json
from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext, WriteTool
from app.modules.ai.domain.admin_tools import AdminToolDef
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.ai import AdminToolBackend
from app.shared.contracts.identity import IdentityDirectory

USER_FIELDS = frozenset({"teacher_id", "curator_id", "head_student_id", "user_id"})
MAX_VALUE_CHARS = 300


class AdminReadTool(ReadTool[ToolArgs]):
    """A read tool of the Administration assistant."""

    def __init__(self, definition: AdminToolDef, backend: AdminToolBackend) -> None:
        """Take name, schema and description from the definition."""
        self.name = definition.name
        self.description = definition.description
        self.args_model = definition.args
        self.backend = backend

    async def run(self, args: ToolArgs, ctx: ToolContext) -> dict[str, Any]:
        """Forward the call to the backend as the admin."""
        return await self.backend.call(self.name, args.as_json(), ctx.actor)


class AdminWriteTool(WriteTool[ToolArgs]):
    """A write tool of the Administration assistant."""

    def __init__(
        self,
        definition: AdminToolDef,
        backend: AdminToolBackend,
        identity: IdentityDirectory,
    ) -> None:
        """Take name, schema and sensitive fields from the definition."""
        self.name = definition.name
        self.description = definition.description + " (needs approval)"
        self.args_model = definition.args
        self.sensitive = definition.sensitive
        self.backend = backend
        self.identity = identity

    async def preview(self, args: ToolArgs, ctx: ToolContext) -> PreviewData:
        """List every argument, naming users; mark sensitive fields."""
        values = args.as_json()
        names = await self._user_names(values)
        fields = [
            PreviewField(
                label_key="ai-field-" + key.replace("_", "-"),
                value=_show(value, names),
                sensitive=key in self.sensitive,
            )
            for key, value in values.items()
        ]
        return PreviewData(
            title_key="ai-preview-" + self.name.replace("_", "-"), fields=fields
        )

    async def _user_names(self, values: dict[str, Any]) -> dict[str, str]:
        ids = [UUID(v) for k, v in values.items() if k in USER_FIELDS and _is_uuid(v)]
        if not ids:
            return {}
        users = await self.identity.get_users(ids)
        return {
            str(uid): f"{u.last_name} {u.first_name}".strip()
            for uid, u in users.items()
        }

    async def run(self, args: ToolArgs, ctx: ToolContext) -> dict[str, Any]:
        """Forward the approved call to the backend as the admin."""
        return await self.backend.call(self.name, args.as_json(), ctx.actor)


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def _show(value: Any, names: dict[str, str]) -> str:
    if isinstance(value, str):
        text = names.get(value, value)
    elif isinstance(value, bool | int | float):
        text = str(value).lower() if isinstance(value, bool) else str(value)
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS] + "…"

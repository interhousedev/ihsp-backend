"""Checks the OpenUI blocks of a finished answer before it is stored.

A valid block is kept as written. A broken one goes once, with its errors, to the
cheap `OPENUI_REPAIR` task (a small coder model) and is validated again; a block that
is still broken (or unsafe) is dropped and the text around it stays. The repair is
an ordinary model call through the recording gateway, so the usage ledger counts it
and a user whose AI access is revoked is refused (the task is in the chat scope).
"""

from app.shared.ai_tasks import ModelProfile
from app.shared.contracts.ai import LlmGateway
from app.shared.openui.blocks import Part, fenced, split_blocks, unfence
from app.shared.openui.catalog import Subset, load_catalog
from app.shared.openui.validate import validate_block

import structlog

log = structlog.get_logger(__name__)

REPAIR_MAX_TOKENS = 900
REPAIR_SYSTEM = (
    "You fix one OpenUI Lang block. Answer with the corrected block only, inside "
    "```{fence} fences, nothing else. Rules: one statement per line, "
    "`identifier = Expression`; the entry is `root = ...`; components take positional "
    "arguments in the order listed; values are strings, numbers, true/false/null, "
    "arrays, objects and references. No $state, no @functions, no HTML, https links "
    "only. Keep the data; remove what cannot be fixed. Allowed components:\n{catalog}"
)


def catalog_lines(subset: Subset) -> str:
    """One line per allowed component: `Name(prop, prop?)  description`."""
    lines = []
    for component in load_catalog().in_subset(subset):
        props = ", ".join(
            p.name + ("" if p.required else "?") + f": {p.kind.type}"
            for p in component.props
        )
        lines.append(f"- {component.name}({props}) - {component.description}")
    return "\n".join(lines)


class OpenUiFinalizer:
    """Repairs or drops the invalid blocks of an answer (see the module doc)."""

    def __init__(
        self,
        llm: LlmGateway,
        profile: ModelProfile,
        *,
        enabled: bool,
        subset: Subset = "chat",
    ) -> None:
        """Keep the gateway, the repair task's profile and the feature flag."""
        self.llm = llm
        self.profile = profile
        self.enabled = enabled
        self.subset = subset

    async def finalize(self, text: str) -> str:
        """The answer with every block valid, repaired or removed."""
        if not self.enabled or f"```{load_catalog().fence}" not in text:
            return text
        limit = load_catalog().limits["max_blocks"]
        out: list[str] = []
        kept = 0
        for part in split_blocks(text):
            if part.kind == "text":
                out.append(part.text)
                continue
            block = await self._block(part) if kept < limit else None
            if block is not None:
                kept += 1
                out.append(block)
        return "".join(out)

    async def _block(self, part: Part) -> str | None:
        if part.kind == "pending":  # the answer stopped inside a block
            return None
        errors = validate_block(part.text, self.subset)
        if not errors:
            return part.raw
        repaired = await self._repair(part.text, errors)
        if repaired is None:
            log.info("openui.block_dropped", errors=errors[:3])
            return None
        tail = "\n" if part.raw.endswith("\n") else ""
        return fenced(repaired) + tail

    async def _repair(self, source: str, errors: list[str]) -> str | None:
        fence = load_catalog().fence
        system = REPAIR_SYSTEM.format(fence=fence, catalog=catalog_lines(self.subset))
        problems = "\n".join(f"- {e}" for e in errors)
        prompt = f"Errors:\n{problems}\n\nBlock:\n```{fence}\n{source}```"
        try:
            response = await self.llm.complete(
                model=self.profile.model,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                max_tokens=self.profile.output_tokens(REPAIR_MAX_TOKENS),
                provider=self.profile.provider(),
                tuning=self.profile.tuning,
            )
        except Exception as error:  # a failed repair only drops the block
            log.warning("openui.repair_failed", error=type(error).__name__)
            return None
        candidate = unfence(str(response.get("text") or ""))
        if validate_block(candidate, self.subset):
            return None
        return candidate

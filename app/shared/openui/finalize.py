"""Checks the OpenUI blocks of a finished answer before it is stored.

A valid block is kept as written. A broken one goes once, with its errors, to the
cheap `OPENUI_REPAIR` task (a small coder model) and is validated again; a block that
is still broken (or unsafe) is dropped and the text around it stays. A block longer
than the catalogue allows is dropped without a call. The repair is an ordinary model
call through the recording gateway, so the usage ledger counts it and a user whose AI
access is revoked is refused (the task is in the chat scope). The caller may also pass
`count`, which receives the tokens of each repair so the chat budget sees them.
"""

from collections.abc import Awaitable, Callable

from app.shared.ai_tasks import ModelProfile
from app.shared.contracts.ai import LlmGateway
from app.shared.openui.blocks import Part, fenced, split_blocks, unfence
from app.shared.openui.catalog import Prop, PropType, Subset, load_catalog
from app.shared.openui.validate import validate_block

import structlog

log = structlog.get_logger(__name__)

UsageCounter = Callable[[int], Awaitable[None]]
REPAIR_MAX_TOKENS = 900  # the floor of the repair answer
REPAIR_CHARS_PER_TOKEN = 2  # a conservative estimate for dense OpenUI source
REPAIR_SYSTEM = (
    "You fix one OpenUI Lang block. Answer with the corrected block only, inside "
    "```{fence} fences, nothing else. Rules: one statement per line, "
    "`identifier = Expression`; the entry is `root = ...`; components take positional "
    "arguments in the order listed; values are strings, numbers, true/false/null, "
    "arrays, objects and references. No $state, no @functions, no HTML, https links "
    "only. Keep the data; remove what cannot be fixed. Allowed components:\n{catalog}"
)


def _kind_text(kind: PropType) -> str:
    """The type of a prop as the prompt writes it, nested fields and values included."""
    if kind.type == "enum":
        return "enum(" + "|".join(kind.values) + ")"
    if kind.type == "list" and kind.of is not None:
        text = f"list<{_kind_text(kind.of)}>"
        return text + (f"[max {kind.max}]" if kind.max else "")
    if kind.type == "object":
        return "{" + ", ".join(_field_text(f) for f in kind.fields) + "}"
    return kind.type


def _field_text(prop: Prop) -> str:
    """One named prop or object field: `name` or `name?` then its type."""
    return prop.name + ("" if prop.required else "?") + f": {_kind_text(prop.kind)}"


def catalog_lines(subset: Subset) -> str:
    """One line per allowed component: `Name(prop, prop?: type)  description`."""
    lines = []
    for component in load_catalog().in_subset(subset):
        props = ", ".join(_field_text(p) for p in component.props)
        lines.append(f"- {component.name}({props}) - {component.description}")
    return "\n".join(lines)


def repair_tokens(source: str) -> int:
    """The output cap of a repair: the floor, or about half the block's characters."""
    scaled = len(source) // REPAIR_CHARS_PER_TOKEN + REPAIR_MAX_TOKENS // 2
    return max(REPAIR_MAX_TOKENS, scaled)


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

    async def finalize(self, text: str, *, count: UsageCounter | None = None) -> str:
        """The answer with every block valid, repaired or removed.

        `count` receives the tokens (input plus output) of every repair call.
        """
        if not self.enabled or f"```{load_catalog().fence}" not in text:
            return text
        limit = load_catalog().limits["max_blocks"]
        out: list[str] = []
        kept = 0
        for part in split_blocks(text):
            if part.kind == "text":
                out.append(part.text)
                continue
            block = await self._block(part, count) if kept < limit else None
            if block is not None:
                kept += 1
                out.append(block)
        return "".join(out)

    async def _block(self, part: Part, count: UsageCounter | None) -> str | None:
        if part.kind == "pending":  # the answer stopped inside a block
            return None
        errors = validate_block(part.text, self.subset)
        if not errors:
            return part.raw
        if len(part.text) > load_catalog().limits["max_block_chars"]:
            log.info("openui.block_dropped", reason="oversized", errors=errors[:3])
            return None
        repaired = await self._repair(part.text, errors, count)
        if repaired is None:
            log.info("openui.block_dropped", reason="unrepairable", errors=errors[:3])
            return None
        log.info("openui.block_repaired", errors=errors[:3])
        tail = "\n" if part.raw.endswith("\n") else ""
        return fenced(repaired) + tail

    async def _repair(
        self, source: str, errors: list[str], count: UsageCounter | None
    ) -> str | None:
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
                max_tokens=self.profile.output_tokens(repair_tokens(source)),
                provider=self.profile.provider(),
                tuning=self.profile.tuning,
            )
        except Exception as error:  # a failed repair only drops the block
            log.warning("openui.repair_failed", error=type(error).__name__)
            return None
        usage = response.get("usage") or {}
        tokens = int(usage.get("input", 0)) + int(usage.get("output", 0))
        if count is not None and tokens > 0:
            await count(tokens)
        candidate = unfence(str(response.get("text") or ""))
        if validate_block(candidate, self.subset):
            return None
        return candidate

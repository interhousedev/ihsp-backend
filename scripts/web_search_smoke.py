"""One real web search through OpenRouter, to check that the hits come back.

    IHSP_OPENROUTER__MODE=real IHSP_OPENROUTER__API_KEY=... \
        uv run python scripts/web_search_smoke.py "photosynthesis" [fast|chat]

Prints the number of hits and, for each, the site and title (never the key). Run it
once after enabling a key: the adapter takes hits from the `url_citation` annotations
only, so an empty list means the engine or surface needs changing
(`IHSP_WEB_SEARCH__SURFACE`, `IHSP_WEB_SEARCH__ENGINE`; docs/reference/notebooklm.md
section 3.8).
"""

import asyncio
import sys

from app.modules.ai.infrastructure.gateway_factory import (
    make_llm_gateway,
    make_web_search_gateway,
)
from app.settings import load_settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.web_search import SearchCall


async def main(query: str, kind: str) -> int:
    """Search once and print the hits."""
    settings = load_settings()
    if settings.openrouter.mode != "real":
        print("set IHSP_OPENROUTER__MODE=real and IHSP_OPENROUTER__API_KEY")
        return 2
    gateway = make_web_search_gateway(settings, make_llm_gateway(settings))
    explain = kind == "fast"
    task = AiTask.DISCOVER if explain else AiTask.WEB_SEARCH
    reply = await gateway.search(
        SearchCall(
            query=query,
            language="en",
            max_results=settings.limits.web_search_max_results,
            explain=explain,
            profile=settings.ai_profile(task),
            exclude_domains=settings.web_search.blocked_domains,
        )
    )
    print(f"{len(reply.hits)} hits, usage {reply.usage}")
    for hit in reply.hits:
        print(f"- {hit.site}: {hit.title} | {hit.why}")
    return 0 if reply.hits else 1


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "photosynthesis"
    mode = sys.argv[2] if len(sys.argv) > 2 else "fast"
    sys.exit(asyncio.run(main(text, mode)))

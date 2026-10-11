"""One real Exa search, to check that the hits and the charge come back.

    IHSP_EXA__MODE=real IHSP_EXA__API_KEY=... \
        uv run python scripts/web_search_smoke.py "photosynthesis" [fast|chat]

Prints the number of hits, the charge and, for each hit, the site, title and the
"why" sentence (never the key). `fast` asks for highlights (the reasons); `chat` does
not, so it costs less. Run it once after the key is set.
"""

import asyncio
import sys

from app.modules.ai.infrastructure.gateway_factory import make_web_search_gateway
from app.settings import load_settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.web_search import SearchCall

from redis.asyncio import Redis


async def main(query: str, kind: str) -> int:
    """Search once and print the hits."""
    settings = load_settings()
    if settings.exa.mode != "real":
        print("set IHSP_EXA__MODE=real and IHSP_EXA__API_KEY")
        return 2
    redis = Redis.from_url(settings.redis.url, decode_responses=True)
    gateway = make_web_search_gateway(settings, redis)
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
    print(f"{len(reply.hits)} hits, cost {reply.cost_micro / 1_000_000:.4f} USD")
    for hit in reply.hits:
        print(f"- {hit.site}: {hit.title} | {hit.why}")
    return 0 if reply.hits else 1


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "photosynthesis"
    mode = sys.argv[2] if len(sys.argv) > 2 else "fast"
    sys.exit(asyncio.run(main(text, mode)))

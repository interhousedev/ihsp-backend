"""Refresh the cached vectors of the retrieval quality set (needs an OpenRouter key).

    cd backend
    IHSP_ENV_FILE="materials/dev.env,?materials/dev-keys/secrets.env" \
        uv run python scripts/vector_eval.py [--model qwen/qwen3-embedding-4b]

Embeds the passages (as documents) and the questions (as queries) of
`tests/notebooks/fixtures/retrieval_eval.json` with the `EMBEDDING` AI task and writes
`retrieval_eval_vectors.json` next to it (half precision, base64). The test
`tests/notebooks/integration/test_retrieval_quality.py` ranks with these vectors, so it
needs no network. A few thousand tokens: well under a cent.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import OpenRouterEmbeddings
from app.modules.vectors.domain.packing import pack
from app.settings import load_settings
from app.settings_ai import AiTaskSettings
from app.shared.ai_tasks import AiTask

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "notebooks" / "fixtures"
FIXTURE = FIXTURES / "retrieval_eval.json"
VECTORS = FIXTURES / "retrieval_eval_vectors.json"


async def main(model: str | None, out: Path) -> None:
    """Embed the fixture and write the vectors file."""
    settings = load_settings()
    key = settings.openrouter.api_key
    if key is None:
        raise SystemExit("IHSP_OPENROUTER__API_KEY is not set")
    if model is not None:
        settings.ai.tasks[AiTask.EMBEDDING] = AiTaskSettings(model=model)
    profile = settings.ai_profile(AiTask.EMBEDDING)
    gateway = OpenRouterGateway(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter.base_url,
        app_url=settings.openrouter.app_url,
        app_title=settings.openrouter.app_title,
        timeout_seconds=settings.openrouter.timeout_seconds,
    )
    embeddings = OpenRouterEmbeddings(gateway, profile)
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    passages = [p for d in data["documents"] for p in d["passages"]]
    totals = {"tokens": 0, "cost_micro": 0}

    async def run(items: list[dict[str, Any]], kind: Any) -> dict[str, str]:
        found: dict[str, str] = {}
        for start in range(0, len(items), embeddings.batch_size):
            batch = items[start : start + embeddings.batch_size]
            result = await embeddings.embed([i["text"] for i in batch], kind=kind)
            totals["tokens"] += result.tokens
            totals["cost_micro"] += result.cost_micro or 0
            for item, vector in zip(batch, result.vectors, strict=True):
                found[item["id"]] = pack(vector)
        return found

    try:
        document_vectors = await run(passages, "document")
        query_vectors = await run(data["questions"], "query")
    finally:
        await gateway.aclose()
    out.write_text(
        json.dumps(
            {
                "model": embeddings.model,
                "dims": embeddings.dims,
                "query_prefix": profile.query_prefix,
                "passages": document_vectors,
                "questions": query_vectors,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"{embeddings.model}: {len(document_vectors)} passages, "
        f"{len(query_vectors)} questions, {totals['tokens']} tokens, "
        f"USD {totals['cost_micro'] / 1e6:.6f} -> {out}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="override the EMBEDDING model")
    parser.add_argument("--out", type=Path, default=VECTORS)
    args = parser.parse_args()
    asyncio.run(main(args.model, args.out))

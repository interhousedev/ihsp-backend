"""Propose subject rankings and experience scores of catalog institutions.

For each institution: Exa search, then the ADMIT_CATALOG_RESEARCH model task
(strict schema). Results are stored as PENDING catalog proposals (unverified)
that a curator reviews; nothing is published here. Run inside the api container:

uv run python scripts/admission_research_rankings.py --as-user <UUID> --limit 5
uv run python scripts/admission_research_rankings.py --dry-run --limit 3
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.modules.admission.application.catalog_rankings_research import (  # noqa: E402
    research,
)
from app.modules.admission.domain.catalog_proposals import (  # noqa: E402
    CatalogProposal,
)
from app.modules.admission.domain.errors import (  # noqa: E402
    CatalogFactInvalidError,
)
from app.modules.admission.domain.intl_facts import clean_facts  # noqa: E402
from app.modules.admission.infrastructure.catalog_proposals_repository import (  # noqa: E402
    SqlCatalogProposalRepository,
)
from app.modules.admission.infrastructure.orm.catalog import (  # noqa: E402
    InstitutionRow,
)
from app.modules.ai.infrastructure.exa import ExaClient  # noqa: E402
from app.modules.ai.infrastructure.gateway_factory import (  # noqa: E402
    make_llm_gateway,
)
from app.modules.notebooks.application.llm import NotebookLlm  # noqa: E402
from app.settings import load_settings  # noqa: E402
from app.shared.clock import SystemClock  # noqa: E402
from app.shared.ids import new_id  # noqa: E402


async def _pages(exa: ExaClient, name: str, country: str) -> list[dict[str, str]]:
    body = {
        "query": f"{name} {country} subject rankings QS THE ARWU student life research",
        "type": "auto",
        "numResults": 6,
        "contents": {"text": {"maxCharacters": 2500}},
    }
    data = await exa.search(body)
    return [
        {"url": r["url"], "text": (r.get("text") or "")[:2500]}
        for r in data.get("results", [])
        if r.get("url", "").startswith("https://")
    ]


async def _run(limit: int | None, dry_run: bool, user: UUID | None) -> list[dict]:
    from app.shared.db.engine import make_engine, make_sessionmaker

    from sqlalchemy import select

    settings = load_settings()
    if settings.exa.api_key is None or settings.exa.mode != "real":
        raise SystemExit("Exa is not configured (IHSP_EXA__MODE=real and a key).")
    if not dry_run and user is None:
        raise SystemExit("--as-user <UUID> is required unless --dry-run.")
    exa = ExaClient(
        api_key=settings.exa.api_key.get_secret_value(),
        base_url=settings.exa.base_url,
        timeout_seconds=settings.exa.timeout_seconds,
    )
    llm = NotebookLlm(make_llm_gateway(settings), settings)
    clock = SystemClock()
    engine = make_engine(settings.database.url, 2)
    report: list[dict] = []
    try:
        async with make_sessionmaker(engine)() as session:
            q = select(InstitutionRow).where(InstitutionRow.status != "archived")
            rows = (await session.scalars(q.order_by(InstitutionRow.name))).all()
            repo = SqlCatalogProposalRepository(session)
            for inst in rows[:limit]:
                now = clock.now()
                pages = await _pages(exa, inst.name, inst.country)
                facts = await research(llm, inst.name, inst.country, pages, now.year)
                try:
                    clean_facts(facts)
                except CatalogFactInvalidError as error:
                    report.append({"name": inst.name, "invalid": error.params})
                    continue
                report.append({"name": inst.name, "facts": sorted(facts)})
                if facts and not dry_run and user is not None:
                    src = next(iter(facts.values()))["source_url"]
                    await repo.add(
                        CatalogProposal(
                            id=new_id(),
                            kind="institution",
                            target_id=inst.id,
                            payload={},
                            source_url=src,
                            note="Web research (unverified)",
                            status="pending",
                            proposed_by=user,
                            created_at=now,
                            facts=facts,
                        )
                    )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await exa.aclose()
        await engine.dispose()
    return report


def main() -> int:
    """Parse the flags, run the research and print a JSON report."""
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--as-user", type=UUID, default=None)
    a = p.parse_args()
    out = asyncio.run(_run(a.limit, a.dry_run, a.as_user))
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Copy org logos and covers from catalog_data/org_media onto admission rows.

uv run python scripts/admission_org_media.py            # apply and commit
uv run python scripts/admission_org_media.py --dry-run  # count only, no changes

Only empty logos and covers are filled; staff-set values are kept.
"""

import argparse
import asyncio
import dataclasses
import json
import sys

from app.modules.admission.infrastructure.org_media import (
    ApplyReport,
    apply_org_media,
    load_org_media,
)


async def _run(dry_run: bool) -> ApplyReport:
    from app.settings import load_settings
    from app.shared.db.engine import make_engine, make_sessionmaker

    settings = load_settings()
    engine = make_engine(settings.database.url, 2)
    try:
        async with make_sessionmaker(engine)() as session:
            report = await apply_org_media(session, load_org_media(), dry_run=dry_run)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        return report
    finally:
        await engine.dispose()


def main() -> int:
    """Parse --dry-run, run the org media apply and print its report as JSON."""
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    out = dataclasses.asdict(asyncio.run(_run(a.dry_run)))
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

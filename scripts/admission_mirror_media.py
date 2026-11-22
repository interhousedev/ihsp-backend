"""Copy external institution and opportunity logos and covers into our S3.

docker exec -i ihsp-api-1 python - [--dry-run] < scripts/admission_mirror_media.py
uv run python scripts/admission_mirror_media.py --dry-run   # count only

Rewrites every https logo or cover URL that is not already ours to
`<public endpoint>/<bucket>/admission/org-media/<sha256>.<ext>`. Unreachable
URLs are kept and listed in the report.
"""

import argparse
import asyncio
import dataclasses
import json
import sys

from app.modules.admission.infrastructure.media_mirror import build_media_mirror
from app.modules.admission.infrastructure.org_media import (
    MirrorReport,
    mirror_existing_media,
)


async def _run(dry_run: bool) -> MirrorReport:
    from app.settings import load_settings
    from app.shared.db.engine import make_engine, make_sessionmaker

    settings = load_settings()
    engine = make_engine(settings.database.url, 2)
    try:
        async with make_sessionmaker(engine)() as session:
            report = await mirror_existing_media(
                session, build_media_mirror(settings), dry_run=dry_run
            )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        return report
    finally:
        await engine.dispose()


def main() -> int:
    """Parse --dry-run, mirror the media and print the report as JSON."""
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    out = dataclasses.asdict(asyncio.run(_run(a.dry_run)))
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

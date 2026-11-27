"""Backfill EMIS attendance history: same as `python -m app backfill-emis-attendance`.

IHSP_ENV_FILE=materials/dev.env uv run python scripts/backfill_emis_attendance.py \
    [--user <UUID> ...]
"""

import sys

from app.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["backfill-emis-attendance", *sys.argv[1:]]))

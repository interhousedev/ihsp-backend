"""Seed demo data: same as `python -m app seed-demo`.

IHSP_ENV_FILE=materials/dev.env uv run python scripts/seed_demo.py
"""

import sys

from app.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["seed-demo"]))

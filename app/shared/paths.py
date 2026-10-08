"""Locations of project folders (the backend root)."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCALES_DIR = BACKEND_ROOT / "locales"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

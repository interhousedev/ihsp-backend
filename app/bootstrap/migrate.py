"""`python -m app migrate`: alembic upgrade heads."""

import argparse

from app.settings import Settings
from app.shared.paths import ALEMBIC_INI

from alembic import command
from alembic.config import Config


def alembic_config(database_url: str) -> Config:
    """Alembic config for the project with the database URL set."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Upgrade every module's branch to its head."""
    command.upgrade(alembic_config(settings.database.url), "heads")
    return 0

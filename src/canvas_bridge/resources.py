"""Locate read-only resources in source checkouts, wheels and native bundles."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def resource_root() -> Path:
    packaged = Path(__file__).resolve().parent / "resources"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2]


def migrate(database_url: str):
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

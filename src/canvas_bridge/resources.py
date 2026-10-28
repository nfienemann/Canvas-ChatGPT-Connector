"""Locate read-only resources in source checkouts, wheels and native bundles."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def resource_root() -> Path:
    packaged = Path(__file__).resolve().parent / "resources"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2]


def migrate(database_url: str, vault_key_file=None):
    config = Config()
    config.set_main_option("script_location", str(resource_root() / "migrations"))
    config.attributes["database_url"] = database_url
    if vault_key_file:
        config.attributes["vault_key_file"] = vault_key_file
    command.upgrade(config, "head")

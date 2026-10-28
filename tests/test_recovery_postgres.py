"""Outdated PostgreSQL schema in a disposable per-test namespace only."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from canvas_bridge.deployment import preflight, target_id, upgrade
from canvas_bridge.resources import resource_root


@pytest.mark.postgres
def test_outdated_postgres_upgrade(settings, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL must name a disposable PostgreSQL database.")
    schema = "fixture_recovery_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    settings.database_url = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    try:
        config = Config()
        config.set_main_option("script_location", str(resource_root() / "migrations"))
        config.attributes["database_url"] = settings.database_url
        config.attributes["vault_key_file"] = settings.vault_key_file
        command.upgrade(config, "62ab7d391c04")
        assert "connections.authentication_state" in preflight(settings)["missing_schema_fields"]
        result = upgrade(settings, target_id(settings.database_url), tmp_path / "before.sealed")
        assert result["preflight"]["service_health"] == "READY"
        assert result["preflight"]["historical_deletion_assurance"] == "unknown"
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()

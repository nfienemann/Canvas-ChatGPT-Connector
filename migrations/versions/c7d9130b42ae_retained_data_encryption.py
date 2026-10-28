"""Encrypt retained academic fields using the existing separately supplied vault."""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import context, op

revision = "c7d9130b42ae"
down_revision = "8d21f4c932ab"
branch_labels = None
depends_on = None

FIELDS = {
    "connections": ["canvas_user", "timezone"],
    "courses": ["source_id", "name"],
    "work_items": ["source_id", "payload"],
    "snapshots": ["course_ids", "items", "coverage", "workload_scope"],
    "local_records": ["payload"],
    "materials": ["source_id", "title", "url", "text", "locators", "limitations", "file_state"],
    "jobs": ["payload"],
    "browser_sessions": ["csrf"],
}
JSON_FIELDS = {
    "payload",
    "course_ids",
    "items",
    "coverage",
    "workload_scope",
    "locators",
    "limitations",
    "file_state",
}


def upgrade():
    from canvas_bridge.storage_crypto import PREFIX, reject_secrets
    from canvas_bridge.vault import Vault

    connection = op.get_bind()
    vault = None
    for name, fields in FIELDS.items():
        with op.batch_alter_table(name) as batch:
            for field in fields:
                batch.alter_column(
                    field, type_=sa.Text(), server_default=None, postgresql_using=f'"{field}"::text'
                )
        table = sa.Table(name, sa.MetaData(), autoload_with=connection)
        primary = list(table.primary_key.columns)[0]
        for row in connection.execute(sa.select(primary, *(table.c[f] for f in fields))).mappings():
            values = {}
            for field in fields:
                value = row[field]
                if value is None or (isinstance(value, str) and value.startswith(PREFIX)):
                    continue
                if vault is None:
                    from canvas_bridge.config import Settings

                    path = context.config.attributes.get("vault_key_file")
                    vault = Vault(Path(path) if path else Settings().vault_key_file)
                if field in JSON_FIELDS and isinstance(value, str):
                    value = json.loads(value)
                    reject_secrets(value)
                values[field] = PREFIX + vault.seal(
                    {"value": value}, "database-field", f"{name}.{field}"
                )
            if values:
                connection.execute(
                    table.update().where(primary == row[primary.name]).values(**values)
                )


def downgrade():
    raise RuntimeError("Encrypted records cannot be downgraded into plaintext storage.")

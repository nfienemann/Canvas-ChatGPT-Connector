"""Independent source storage and deployment key binding; no authority backfill."""

import sqlalchemy as sa
from alembic import op

revision = "d914cb092014"
down_revision = "c7d9130b42ae"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "independent_resources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("version_hash", sa.String(64), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_independent_resources_owner", "independent_resources", ["owner"])
    op.create_index(
        "ix_independent_resources_version_hash", "independent_resources", ["version_hash"]
    )
    op.create_table(
        "deployment_state",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Recovery requires a reviewed encrypted backup; destructive or plaintext downgrade is unsupported."
    )

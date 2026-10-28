"""Keep workload view selection separate from source inventory."""

import sqlalchemy as sa
from alembic import op

revision = "62ab7d391c04"
down_revision = "4be2ca7831f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "snapshots", sa.Column("workload_scope", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade():
    op.drop_column("snapshots", "workload_scope")

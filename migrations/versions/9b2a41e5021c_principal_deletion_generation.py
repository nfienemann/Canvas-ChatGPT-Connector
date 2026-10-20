"""Fence account deletion against pending authorization and browser sessions."""

import sqlalchemy as sa
from alembic import op

revision = "9b2a41e5021c"
down_revision = "001f5d856728"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "principal_states",
        sa.Column("owner", sa.String(64), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
    )
    op.add_column(
        "oauth_states", sa.Column("generation", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "browser_sessions",
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("browser_sessions", "generation")
    op.drop_column("oauth_states", "generation")
    op.drop_table("principal_states")

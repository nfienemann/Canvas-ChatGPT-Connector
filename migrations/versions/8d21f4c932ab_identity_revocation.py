"""Persist application revocation and explicit upstream verification state."""

import sqlalchemy as sa
from alembic import op

revision = "8d21f4c932ab"
down_revision = "62ab7d391c04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("principal_states", sa.Column("tokens_valid_after", sa.DateTime(timezone=True)))
    # Existing credentials must be verified again, never promoted by migration.
    op.add_column(
        "connections",
        sa.Column(
            "authentication_state", sa.String(30), nullable=False, server_default="unverified"
        ),
    )


def downgrade():
    op.drop_column("connections", "authentication_state")
    op.drop_column("principal_states", "tokens_valid_after")

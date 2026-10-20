"""Distinguish page and file resources without changing existing page identities."""

import sqlalchemy as sa
from alembic import op

revision = "1c8d7b420ad1"
down_revision = "9b2a41e5021c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "materials", sa.Column("kind", sa.String(20), nullable=False, server_default="page")
    )


def downgrade():
    # A previous binary cannot interpret a file ID as a page ID. Remove those
    # derived records before removing the discriminator on an explicit rollback.
    op.execute("DELETE FROM materials WHERE kind <> 'page'")
    op.drop_column("materials", "kind")

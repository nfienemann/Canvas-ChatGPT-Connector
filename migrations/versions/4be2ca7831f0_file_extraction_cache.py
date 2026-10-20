"""Track bounded document extraction versions and coverage."""

import sqlalchemy as sa
from alembic import op

revision = "4be2ca7831f0"
down_revision = "1c8d7b420ad1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "materials", sa.Column("file_state", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade():
    op.execute(
        "UPDATE materials SET text='', version_hash='', locators='[]', limitations='[]' WHERE kind='file'"
    )
    op.drop_column("materials", "file_state")

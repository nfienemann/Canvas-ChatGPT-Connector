"""Bounded private-library operations and managed encrypted backup inventory."""

from alembic import op

from canvas_bridge.library.models import BackupRecord, Metric, OperationLease

revision = "b39f81ca26de"
down_revision = "a28e70b915cd"
branch_labels = None
depends_on = None


def upgrade():
    for model in (OperationLease, Metric, BackupRecord):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError(
        "Preserve durable originals and backup/deletion accounting; destructive downgrade is unsupported."
    )

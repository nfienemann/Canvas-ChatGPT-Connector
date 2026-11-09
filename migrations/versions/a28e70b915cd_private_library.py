"""Durable private library; disabled by default, no legacy retention conversion."""

from alembic import op

from canvas_bridge.library.models import Base, install_sqlite_constraints

revision = "a28e70b915cd"
down_revision = "f17a6b204c31"
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())
    install_sqlite_constraints(op.get_bind())


def downgrade():
    raise RuntimeError(
        "Preserve durable originals and deletion fences. Disable new library writes and use a compatible maintenance build; destructive downgrade is unsupported."
    )

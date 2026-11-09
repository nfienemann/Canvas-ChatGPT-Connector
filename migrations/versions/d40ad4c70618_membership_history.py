"""Bounded membership listing history, separate from current authority."""

import sqlalchemy as sa
from alembic import op

revision = "d40ad4c70618"
down_revision = "b39f81ca26de"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("last_course_list_attempt_at", "last_complete_course_list_at"):
        op.add_column("connections", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column("connections", sa.Column("last_course_list_outcome", sa.String(16)))
    # SQLite CURRENT_TIMESTAMP only has second precision. Compare Julian days there.
    connections = sa.table(
        "connections",
        sa.column("state"),
        sa.column("entitlement_at"),
        sa.column("last_complete_course_list_at"),
    )
    evidence = connections.c.entitlement_at
    valid = (
        sa.func.julianday(evidence) <= sa.func.julianday("now")
        if op.get_context().dialect.name == "sqlite"
        else evidence <= sa.func.current_timestamp()
    )
    op.execute(
        connections.update()
        .where(connections.c.state == "active", valid)
        .values(last_complete_course_list_at=evidence)
    )


def downgrade():
    for name in (
        "last_course_list_outcome",
        "last_complete_course_list_at",
        "last_course_list_attempt_at",
    ):
        op.drop_column("connections", name)

"""Cooperative PostgreSQL writer fence, held for each physical Store connection."""

from contextvars import ContextVar
from pathlib import Path

LOCK_ID = 1128419922
upgrade_connection = ContextVar("bridge_upgrade_connection", default=False)


def fence_connection(dbapi_connection, connection_record):
    if upgrade_connection.get():
        return
    if (Path.cwd() / ".database-maintenance").exists():
        raise RuntimeError("CANVAS_BRIDGE_DATABASE_MAINTENANCE")
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock_shared(%s)", (LOCK_ID,))
        allowed = cursor.fetchone()[0]
    dbapi_connection.commit()
    if not allowed:
        raise RuntimeError("CANVAS_BRIDGE_DATABASE_MAINTENANCE")

from contextlib import closing

from alembic import context

from canvas_bridge.config import Settings
from canvas_bridge.storage import Base, Store

target_metadata = Base.metadata
database_url = context.config.attributes.get("database_url") or Settings().database_url

if context.is_offline_mode():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    # Explicit upgrade orchestration holds its maintenance lock on this same session.
    connection = context.config.attributes["connection"]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    with closing(Store(database_url)) as store, store.engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            # sqlite3 legacy mode does not begin a transaction for DDL. Include
            # every revision so a later refusal rolls back earlier schema changes.
            connection.exec_driver_sql("BEGIN")
        context.configure(connection=connection, target_metadata=target_metadata)
        context.run_migrations()

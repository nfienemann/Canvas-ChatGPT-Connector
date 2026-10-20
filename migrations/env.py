from alembic import context

from canvas_bridge.config import Settings
from canvas_bridge.storage import Base, Store

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=Settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    store = Store(Settings().database_url)
    with store.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

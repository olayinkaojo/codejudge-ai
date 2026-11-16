from alembic import context

from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base, database_engine


def run_migrations():
    if context.is_offline_mode():
        context.configure(url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        supplied = context.config.attributes.get("connection")
        if supplied is not None:
            migrate_connection(supplied)
        else:
            engine = database_engine()
            try:
                with engine.connect() as connection:
                    migrate_connection(connection)
            finally:
                engine.dispose()


def migrate_connection(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()

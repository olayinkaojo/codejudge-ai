from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base


def run_migrations():
    if context.is_offline_mode():
        context.configure(url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()


run_migrations()

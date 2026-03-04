"""
Alembic environment configuration.

Uses psycopg2 (sync) for migrations to avoid asyncpg + PgBouncer
prepared statement issues. The DATABASE_URL is rewritten from
postgresql+asyncpg:// to postgresql+psycopg2:// if needed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.core.config import settings

# Import all models for auto-generation to detect changes
from src.models import Base  # noqa: F401 - imports all models via __init__

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Normalize URL to psycopg2 for sync migrations
_db_url = settings.database_url
for prefix in ("postgresql+asyncpg://", "postgres://"):
    _db_url = _db_url.replace(prefix, "postgresql+psycopg2://")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using sync psycopg2."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

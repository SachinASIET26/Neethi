"""Alembic environment configuration for async SQLAlchemy.

Reads DATABASE_URL from environment variables to avoid credentials in source code.
Supports both online (with DB connection) and offline (SQL script generation) modes.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models so Alembic can detect changes via autogenerate
from backend.db.models.legal_foundation import Base  # noqa: F401

# ---------------------------------------------------------------------------
# Alembic config object — provides access to alembic.ini values
# ---------------------------------------------------------------------------
config = context.config

# Override the SQLAlchemy URL from the environment variable
# This ensures real credentials are never stored in alembic.ini
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object for autogenerate support
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline mode — generate SQL without a live connection
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL, without an Engine.
    Calls to context.execute() emit SQL to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — run migrations against a live database
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations via a sync wrapper."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live async database."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

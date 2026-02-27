"""Async SQLAlchemy database configuration for Neethi AI.

Provides:
- Async engine connected to Supabase PostgreSQL via DATABASE_URL env var
- AsyncSession factory
- get_db() FastAPI dependency for session injection
- health_check() for system health endpoint
"""

import os
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models.legal_foundation import Base

# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/neethi_dev",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,           # Set True only for local debugging; never in production
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,    # Recycle connections every 30 minutes
    pool_pre_ping=True,   # Verify connection health before use
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # Prevent lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for use as a FastAPI dependency.

    Usage in an endpoint::

        @router.get("/sections/{section_id}")
        async def get_section(section_id: str, db: AsyncSession = Depends(get_db)):
            ...

    The session is automatically committed on success or rolled back on exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def health_check() -> bool:
    """Verify PostgreSQL connectivity by running SELECT 1.

    Returns:
        True if the database is reachable, False otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Table creation helper (for testing / first-time setup)
# ---------------------------------------------------------------------------

async def create_all_tables() -> None:
    """Create all tables defined in the models.

    Use Alembic migrations in production.
    This function is provided for development and testing convenience.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """Drop all tables. Destructive — never call in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

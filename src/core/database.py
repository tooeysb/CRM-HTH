"""
Database session management with PgBouncer compatibility.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings

# Synchronous engine for FastAPI routes (with PgBouncer compatibility)
# Note: Using psycopg2 (sync) driver with Transaction pooler
sync_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": "-c statement_timeout=30000"},  # 30s timeout
)

# Synchronous engine for Celery workers
# Higher pool size + overflow for parallel backfill workers; recycle to avoid Supabase timeouts.
worker_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
)

# Async engine for background tasks (with PgBouncer compatibility)
# Construct async URL from sync URL
async_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
async_engine = create_async_engine(
    async_url,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},  # Required for PgBouncer
)

# Session factories
SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)

WorkerSessionLocal = sessionmaker(
    bind=worker_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # Prevent detached instance errors after session close/reopen
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
)


def get_sync_db() -> Session:
    """Get synchronous database session for FastAPI routes."""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncSession:
    """Get asynchronous database session for background tasks."""
    async with AsyncSessionLocal() as session:
        yield session

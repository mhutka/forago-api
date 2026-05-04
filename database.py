"""
Database connection and utilities for ForaGo Backend.
Implements dependency injection pattern for FastAPI.
"""

import os
import ssl
import logging
from typing import Optional, Any, AsyncGenerator
from contextlib import asynccontextmanager

from config import settings

logger = logging.getLogger(__name__)

# Global connection pool
_pool: Optional[Any] = None


def _resolve_db_ssl_context() -> Any:
    """Resolve SSL context for database connection."""
    mode = settings.db_ssl_mode or (
        "require" if settings.is_production() else "disable"
    )

    if mode == "disable":
        return False

    if mode == "require":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    return ssl.create_default_context()


async def init_db() -> None:
    """Initialize database connection pool."""
    import asyncpg  # lazy import – only needed in db mode

    global _pool
    if _pool is not None:
        logger.warning("Database pool already initialized")
        return

    try:
        ssl_context = _resolve_db_ssl_context()
        _pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            ssl=ssl_context,
            statement_cache_size=settings.db_statement_cache_size,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            command_timeout=settings.db_command_timeout,
        )
        logger.info(
            "DB pool initialized: %s@%s:%d/%s (min_size=%d, max_size=%d)",
            settings.db_user,
            settings.db_host,
            settings.db_port,
            settings.db_name,
            settings.db_pool_min_size,
            settings.db_pool_max_size,
        )
    except Exception as e:
        logger.error("Database pool initialization failed: %s", e, exc_info=True)
        raise


async def close_db() -> None:
    """Close database connection pool."""
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
            _pool = None
            logger.info("DB pool closed")
        except Exception as e:
            logger.error("Error closing database pool: %s", e, exc_info=True)
            raise


def get_pool() -> Any:
    """Get the global connection pool.

    Returns:
        asyncpg.Pool: Database connection pool

    Raises:
        RuntimeError: If pool not initialized
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call init_db() first."
        )
    return _pool


async def get_db() -> AsyncGenerator[Any, None]:
    """FastAPI dependency for database connections.

    Yields:
        asyncpg.Connection: Database connection from pool

    Raises:
        RuntimeError: If pool not initialized
    """
    pool = get_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[Any, None]:
    """Context manager for database connections.

    Usage:
        async with get_db_context() as conn:
            result = await conn.fetch("SELECT ...")

    Yields:
        asyncpg.Connection: Database connection from pool
    """
    pool = get_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


async def get_db_connection() -> Any:
    """Backward-compatible helper returning one acquired DB connection.

    Existing query helpers call this function directly and close/release later.
    """
    pool = get_pool()
    return await pool.acquire()


async def release_db_connection(conn: Any) -> None:
    """Backward-compatible helper to release an acquired DB connection."""
    pool = get_pool()
    await pool.release(conn)


async def run_migrations() -> None:
    """Run SQL migrations from migrations/ folder.

    Migrations are executed in lexicographic order (001, 002, ...).
    """
    pool = get_pool()
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    if not os.path.exists(migrations_dir):
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    # Get all .sql files, sorted by name
    migration_files = sorted(
        [f for f in os.listdir(migrations_dir) if f.endswith(".sql")]
    )

    if not migration_files:
        logger.info("No migration files found")
        return

    async with pool.acquire() as conn:
        for filename in migration_files:
            filepath = os.path.join(migrations_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    sql = f.read()
                await conn.execute(sql)
                logger.info("Migration executed: %s", filename)
            except Exception as e:
                logger.error(
                    "Migration failed for %s: %s",
                    filename,
                    e,
                    exc_info=True,
                )
                raise

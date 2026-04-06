"""
Database connection and utilities for ForaGo Backend
"""

import os
from typing import Optional, Any
from dotenv import load_dotenv

load_dotenv()

# Database connection settings
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "forago")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def _resolve_db_ssl() -> bool:
    """Resolve DB SSL mode from env, defaulting to enabled in production."""
    raw_value = os.getenv("DB_SSL", "").strip().lower()
    if not raw_value:
        return ENVIRONMENT == "production"
    return raw_value in {"1", "true", "yes", "on", "require"}


DB_SSL = _resolve_db_ssl()

# Global connection pool
_pool: Optional[Any] = None


async def init_db():
    """Initialize database connection pool."""
    import asyncpg  # lazy import – only needed in db mode
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                ssl=DB_SSL,
                min_size=5,
                max_size=20,
                command_timeout=60,
            )
            print(
                f"✓ DB pool initialized: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} (ssl={DB_SSL})"
            )
        except Exception as e:
            print(f"✗ DB pool init failed: {e}")
            raise


async def close_db():
    """Close database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        print("✓ DB pool closed")


def get_pool() -> Any:
    """Get the global connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def run_migrations():
    """Run SQL migrations from migrations/ folder."""
    pool = get_pool()
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    
    if not os.path.exists(migrations_dir):
        print(f"✗ Migrations directory not found: {migrations_dir}")
        return
    
    # Get all .sql files in migrations/, sorted by name (lexicographic order ensures 001, 002, 003...)
    migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith(".sql")])
    
    async with pool.acquire() as conn:
        for filename in migration_files:
            filepath = os.path.join(migrations_dir, filename)
            with open(filepath, "r") as f:
                sql = f.read()
            try:
                await conn.execute(sql)
                print(f"✓ {filename} executed")
            except Exception as e:
                print(f"✗ {filename} failed: {e}")
                raise


async def get_db_connection():
    """Get a single connection from the pool (for use in routes)."""
    pool = get_pool()
    return await pool.acquire()


async def release_db_connection(conn):
    """Release a pooled connection acquired via get_db_connection()."""
    pool = get_pool()
    await pool.release(conn)

"""
S.T.R.A.N.D — Database Connection Manager

Supports both:
1. Neon Cloud PostgreSQL (PostGIS) via DATABASE_URL
2. Local DuckDB (Spatial Extension) as offline fallback

Provides a thread-safe singleton connection and read-only connections.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from strand.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_connection: Any = None
_db_type: str = "unknown"


class PostgresConnectionWrapper:
    """
    Adapter wrapping psycopg2 connection to provide DuckDB-compatible API:
    - .execute(sql, params) with '?' parameter placeholder translation to '%s'
    - .fetchone(), .fetchall(), .description
    - Automatic transaction commit on data modification statements
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._cur: Any = None

    @property
    def description(self) -> Any:
        return self._cur.description if self._cur else None

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> PostgresConnectionWrapper:
        # Convert DuckDB '?' parameter placeholders to PostgreSQL '%s'
        pg_sql = sql.replace("?", "%s")
        self._cur = self._conn.cursor()

        if params is not None:
            self._cur.execute(pg_sql, tuple(params))
        else:
            self._cur.execute(pg_sql)

        # Auto-commit DDL and DML operations
        stripped = pg_sql.strip().upper()
        if not stripped.startswith(("SELECT", "WITH", "EXPLAIN")):
            self._conn.commit()

        return self

    def fetchone(self) -> Any:
        return self._cur.fetchone() if self._cur else None

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall() if self._cur else []

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_db() -> Any:
    """
    Get the global database connection singleton.

    Uses Neon PostgreSQL (PostGIS) if DATABASE_URL is configured in .env,
    otherwise initializes local DuckDB.

    Returns:
        Connection instance with spatial capabilities.
    """
    global _connection, _db_type
    if _connection is not None:
        return _connection

    with _lock:
        if _connection is not None:
            return _connection

        settings = get_settings()

        # Check if Neon / PostgreSQL URL is provided
        if settings.database_url and settings.database_url.startswith(("postgres://", "postgresql://")):
            import psycopg2

            logger.info("Connecting to Neon PostgreSQL...")
            pg_conn = psycopg2.connect(settings.database_url)

            # Ensure PostGIS is activated
            with pg_conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            pg_conn.commit()

            logger.info("Connected to Neon PostgreSQL with PostGIS extension")
            _connection = PostgresConnectionWrapper(pg_conn)
            _db_type = "neon"
            return _connection

        # Fallback to local DuckDB
        import duckdb

        db_path = Path(settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Initializing DuckDB at %s", db_path)
        conn = duckdb.connect(str(db_path))

        conn.execute("INSTALL spatial;")
        conn.execute("LOAD spatial;")
        logger.info("DuckDB spatial extension loaded")

        _connection = conn
        _db_type = "duckdb"
        return _connection


def get_readonly_db() -> Any:
    """
    Get a read-only database connection for the copilot module.

    Returns:
        Isolated read-only connection instance.
    """
    settings = get_settings()

    if settings.database_url and settings.database_url.startswith(("postgres://", "postgresql://")):
        import psycopg2

        pg_conn = psycopg2.connect(settings.database_url)
        with pg_conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = TRUE;")
            cur.execute("SET statement_timeout = '30s';")
        pg_conn.commit()
        return PostgresConnectionWrapper(pg_conn)

    import duckdb

    db_path = Path(settings.database_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run the pipeline first."
        )

    conn = duckdb.connect(str(db_path), read_only=True)
    conn.execute("LOAD spatial;")
    conn.execute("SET statement_timeout='30s';")
    return conn


def close_db() -> None:
    """Close the global database connection."""
    global _connection, _db_type
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
            logger.info("Database connection closed (%s)", _db_type)


def check_db_health() -> str:
    """
    Check database connectivity and return status string.

    Returns:
        'connected (neon-postgis)' or 'connected (duckdb)' if healthy.
    """
    try:
        conn = get_db()
        result = conn.execute("SELECT 1 AS health_check").fetchone()
        if result and result[0] == 1:
            return f"connected ({_db_type})"
        return "unhealthy"
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return f"disconnected: {e}"

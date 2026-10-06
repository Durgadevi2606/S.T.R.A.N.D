"""
S.T.R.A.N.D — DuckDB Connection Manager

Provides a thread-safe singleton connection to the DuckDB spatial database.
Supports read-only connections for the copilot (security isolation).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import duckdb

from strand.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None


def get_db() -> duckdb.DuckDBPyConnection:
    """
    Get the global DuckDB connection singleton.

    Creates the database file and installs the spatial extension on first call.
    Thread-safe via threading lock.

    Returns:
        A DuckDB connection with the spatial extension loaded.
    """
    global _connection
    if _connection is not None:
        return _connection

    with _lock:
        # Double-check after acquiring lock
        if _connection is not None:
            return _connection

        settings = get_settings()
        db_path = Path(settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Initializing DuckDB at %s", db_path)
        conn = duckdb.connect(str(db_path))

        # Install and load spatial extension
        conn.execute("INSTALL spatial;")
        conn.execute("LOAD spatial;")
        logger.info("DuckDB spatial extension loaded")

        _connection = conn
        return _connection


def get_readonly_db() -> duckdb.DuckDBPyConnection:
    """
    Get a read-only DuckDB connection for the copilot module.

    This prevents any data modification via copilot-generated SQL queries.
    Each call creates a new connection to ensure isolation.

    Returns:
        A read-only DuckDB connection with the spatial extension loaded.
    """
    settings = get_settings()
    db_path = Path(settings.database_path)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run the pipeline first."
        )

    conn = duckdb.connect(str(db_path), read_only=True)
    conn.execute("LOAD spatial;")

    # Set query timeout to prevent resource exhaustion
    conn.execute("SET statement_timeout='30s';")

    return conn


def close_db() -> None:
    """Close the global DuckDB connection."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
            logger.info("DuckDB connection closed")


def check_db_health() -> str:
    """
    Check database connectivity and return status string.

    Returns:
        'connected' if healthy, 'disconnected' with error details otherwise.
    """
    try:
        conn = get_db()
        result = conn.execute("SELECT 1 AS health_check").fetchone()
        if result and result[0] == 1:
            return "connected"
        return "unhealthy"
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return f"disconnected: {e}"

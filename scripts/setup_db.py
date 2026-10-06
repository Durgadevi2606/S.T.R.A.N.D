#!/usr/bin/env python3
"""
S.T.R.A.N.D — Database Setup Script

Initializes the DuckDB spatial database schema.
Run this once before starting the application.

Usage:
    python scripts/setup_db.py
"""

import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from strand.config import get_settings
from strand.db.connection import get_db, close_db
from strand.db.migrations import run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Initialize the database and run all migrations."""
    logger.info("=" * 60)
    logger.info("S.T.R.A.N.D Database Setup")
    logger.info("=" * 60)

    settings = get_settings()
    settings.ensure_directories()

    logger.info("Database path: %s", settings.database_path)

    try:
        run_migrations()
        logger.info("✅ Database schema created successfully")

        # Verify by listing tables
        conn = get_db()
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()

        logger.info("Tables created (%d):", len(tables))
        for (table_name,) in tables:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            logger.info("  📋 %s (%d rows)", table_name, row_count)

    except Exception as e:
        logger.error("❌ Database setup failed: %s", e)
        sys.exit(1)
    finally:
        close_db()

    logger.info("=" * 60)
    logger.info("Setup complete. Ready to run S.T.R.A.N.D.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

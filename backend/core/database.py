"""
SQLite database setup with SQLAlchemy.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.pool import StaticPool

from backend.config import settings

# Create engine with SQLite-specific settings
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={
        "check_same_thread": False,  # Allow multi-threaded access
        "timeout": 30,  # 30 second timeout for locks
    },
    poolclass=StaticPool,  # Single connection pool for SQLite
    echo=settings.DEBUG,
)


# Enable WAL mode and busy timeout for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure SQLite for better concurrency."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints.
    Yields a database session and ensures cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Use in non-FastAPI code (workers, scripts).
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize database tables.
    Call this on application startup.
    """
    from backend.models.database import Job, Compound  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Apply schema migrations for existing databases
    _apply_migrations()


def _apply_migrations() -> None:
    """Apply any pending schema migrations.

    SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS,
    so we check if columns exist first.
    """
    import logging
    logger = logging.getLogger(__name__)

    with engine.connect() as conn:
        # Get existing columns in jobs table
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        existing_columns = {row[1] for row in result.fetchall()}

        # Add session_id column if missing
        if 'session_id' not in existing_columns:
            logger.info("Adding session_id column to jobs table")
            conn.execute(text("ALTER TABLE jobs ADD COLUMN session_id VARCHAR(36)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_session_id ON jobs(session_id)"))

        # Add batch_id column if missing
        if 'batch_id' not in existing_columns:
            logger.info("Adding batch_id column to jobs table")
            conn.execute(text("ALTER TABLE jobs ADD COLUMN batch_id VARCHAR(36)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_batch_id ON jobs(batch_id)"))

        # Add partial index for pending jobs (speeds up scheduler queries)
        # This index is critical for large batch performance (1000+ jobs)
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_jobs_pending_queue
            ON jobs(status, created_at)
            WHERE status = 'pending'
        """))

        conn.commit()

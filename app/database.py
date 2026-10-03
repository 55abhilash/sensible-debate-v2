"""
SQLAlchemy setup.

We use a plain synchronous engine. Traffic per debate is tiny (two people
typing occasionally), so there is no need for an async driver - it would
only add complexity. SQLite is the default so the project runs with zero
setup; point SD_DATABASE_URL at Postgres/MySQL for a multi-instance setup.
"""
import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

logger = logging.getLogger("sensible_debate.database")

# Make sure a local ./data directory exists for the default SQLite file.
if settings.DATABASE_URL.startswith("sqlite"):
    os.makedirs("data", exist_ok=True)

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables if they don't already exist. Called on every process's
    startup - which means when autoscaling launches more than one instance
    at once, more than one process can race to create the same tables. The
    end state (tables exist) is all that actually matters, so a race lost
    to another process is logged and ignored rather than crashing startup."""
    from app import models  # noqa: F401  (ensures models are registered)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.warning("init_db: create_all raised %r - likely a concurrent-startup race between instances; continuing", exc)


def get_session():
    """Plain session for use outside of request scope (debate room code,
    which is driven by websocket events rather than a single HTTP
    request). Caller is responsible for closing it."""
    return SessionLocal()


def get_db():
    """FastAPI dependency: one session per HTTP request, closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

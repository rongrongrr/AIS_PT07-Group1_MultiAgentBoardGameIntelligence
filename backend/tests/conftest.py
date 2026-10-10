"""Shared test setup: an isolated SQLite file and a clean schema per test."""

import os
import tempfile

# Must be set before app.models.db is imported anywhere.
_TMP = os.path.join(tempfile.gettempdir(), "tiles_pytest.db")
os.environ.setdefault("TILES_DB_PATH", _TMP)
os.environ.setdefault("TILES_MLFLOW_DISABLED", "1")   # tests that exercise tracking opt in

import pytest  # noqa: E402

from app.models.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture
def db():
    """A DB session on a freshly created schema."""
    Base.metadata.drop_all(bind=engine)
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

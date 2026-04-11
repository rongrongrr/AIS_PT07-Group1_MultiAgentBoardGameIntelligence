"""SQLAlchemy models and database setup for TILES."""

import os
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DB_PATH = os.environ.get(
    "TILES_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "db", "tiles.db"),
)
DB_URL = f"sqlite:///{os.path.abspath(DB_PATH)}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    room_name = Column(String, nullable=False)
    platform_url = Column(
        String, nullable=False, default="https://buddyboardgames.com/azul"
    )
    browser_mode = Column(String, nullable=False, default="headless")
    status = Column(String, nullable=False, default="created")
    player_config = Column(Text, nullable=False)  # JSON
    profiler_config = Column(Text, nullable=True)  # JSON
    move_timeout_sec = Column(Integer, nullable=False, default=10)
    stuck_abort_sec = Column(Integer, nullable=False, default=3)
    final_scores = Column(Text, nullable=True)  # JSON: {"Alice": 21, "Bob": 15}
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class GameState(Base):
    __tablename__ = "game_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)
    step_id = Column(Integer, nullable=False)
    state_json = Column(Text, nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("session_id", "step_id"),)


class Move(Base):
    __tablename__ = "moves"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)
    step_id = Column(Integer, nullable=False)
    player_name = Column(String, nullable=False)
    system_tag = Column(String, nullable=True)
    action_json = Column(Text, nullable=False)  # JSON
    decision_time_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("session_id", "step_id"),)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)
    player_name = Column(String, nullable=False)
    profiler_tag = Column(String, nullable=False)
    profile_json = Column(Text, nullable=False)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)


class MLModel(Base):
    __tablename__ = "ml_models"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    model_type = Column(String, nullable=False)  # player | profiler | unified
    config_json = Column(Text, nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Create all tables."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

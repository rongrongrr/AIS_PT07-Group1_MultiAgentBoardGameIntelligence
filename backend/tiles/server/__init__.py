"""TILES FastAPI server (see docs/API.md for the contract)."""

from .app import app, create_app

__all__ = ["app", "create_app"]

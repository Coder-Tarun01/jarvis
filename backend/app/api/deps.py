"""Shared FastAPI dependencies."""

from ..core.db import get_db
from ..core.security import require_auth

__all__ = ["get_db", "require_auth"]

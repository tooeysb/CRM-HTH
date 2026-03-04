"""
API key authentication middleware.

Validates X-API-Key header against settings.secret_key.
Single-user system: after key validation, returns the sole User row.
"""

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    api_key: str | None = Security(API_KEY_HEADER),
) -> None:
    """Validate API key against settings.secret_key."""
    if not api_key or api_key != settings.secret_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def get_current_user(
    _: None = Depends(require_api_key),
    db: Session = Depends(get_sync_db),
) -> User:
    """Return the authenticated user after API key validation."""
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user configured")
    return user

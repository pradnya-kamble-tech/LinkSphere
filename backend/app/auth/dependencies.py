from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_db
from app.core.security import is_valid_origin
from app.users.models import User
from app.auth.service import get_valid_session


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Validate HttpOnly session_token cookie and return authenticated User, or raise 401."""
    raw_token = request.cookies.get("session_token")
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    session_data = get_valid_session(db, raw_token)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked session"
        )

    _, user = session_data
    return user


def verify_csrf_origin(request: Request) -> None:
    """Enforce Origin header match on state-changing requests."""
    origin = request.headers.get("origin")
    if not is_valid_origin(origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Origin mismatch"
        )

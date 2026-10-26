
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.user_session import UserSession


def _hash_token(token: str) -> str:
    """Hash a session token before storing or looking it up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    db: Session,
    user_id: UUID,
) -> tuple[str, UserSession]:
    """Create a secure session and return its raw token and record."""
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    session_record = UserSession(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(
            seconds=settings.session_max_age_seconds
        ),
    )

    db.add(session_record)
    db.commit()
    db.refresh(session_record)

    return raw_token, session_record


def get_user_from_session(
    db: Session,
    raw_token: str | None,
) -> User | None:
    """Return the user only when the session is valid."""
    if not raw_token or len(raw_token) > 200:
        return None

    now = datetime.now(timezone.utc)

    session_record = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == _hash_token(raw_token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )

    if session_record is None:
        return None

    return db.scalar(
        select(User).where(User.id == session_record.user_id)
    )


def revoke_session(
    db: Session,
    raw_token: str | None,
) -> bool:
    """Revoke a session so it cannot authenticate again."""
    if not raw_token or len(raw_token) > 200:
        return False

    session_record = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == _hash_token(raw_token),
            UserSession.revoked_at.is_(None),
        )
    )

    if session_record is None:
        return False

    session_record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    session_token: Annotated[
        str | None,
        Cookie(alias=settings.session_cookie_name),
    ] = None,
) -> User:
    """Require a valid session cookie for protected endpoints."""
    user = get_user_from_session(db, session_token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return user


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Set the browser's HTTP-only session cookie."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the browser's session cookie."""
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )

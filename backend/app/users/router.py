import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.db import get_db
from app.auth.dependencies import (
    get_current_user,
    get_current_session_and_user,
    verify_csrf_origin,
)
from app.users.models import User
from app.auth.models import AuthIdentity, Session as SessionModel
from app.auth.service import is_session_active

router = APIRouter(prefix="/me", tags=["users"])


@router.get("")
def get_me(current_user: User = Depends(get_current_user)):
    """Return authenticated user profile or 401."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/identities")
def get_my_identities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return list of user's linked OAuth identities:
    provider, email_verified, and created_at only.
    Never returns provider_user_id or email field.
    """
    identities = (
        db.query(AuthIdentity)
        .filter(AuthIdentity.user_id == current_user.id)
        .order_by(AuthIdentity.created_at.asc())
        .all()
    )
    return [
        {
            "provider": ident.provider,
            "email_verified": ident.email_verified,
            "created_at": ident.created_at.isoformat() if ident.created_at else None,
        }
        for ident in identities
    ]


@router.get("/sessions")
def get_my_sessions(
    current_session_and_user: tuple = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
):
    """
    Return list of active non-expired, non-revoked sessions for current user.
    Uses shared is_session_active check.
    Never returns token_hash.
    """
    current_session, user = current_session_and_user
    now = datetime.now(timezone.utc)

    # Fetch all sessions for user that have not been explicitly revoked
    raw_sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user.id,
            SessionModel.revoked_at.is_(None),
        )
        .order_by(SessionModel.created_at.desc())
        .all()
    )

    active_sessions = []
    for s in raw_sessions:
        if is_session_active(s, now):
            active_sessions.append({
                "id": str(s.id),
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "is_current": (s.id == current_session.id),
            })

    return active_sessions


@router.delete("/sessions/{session_id}")
def revoke_single_session(
    session_id: str,
    request: Request,
    current_session_and_user: tuple = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf_origin),
):
    """
    Revoke a single session by setting revoked_at.
    Owner-only; 404 for another user's or unknown session id.
    422 for malformed UUID.
    Clears session cookie if current session was revoked.
    """
    current_session, user = current_session_and_user

    try:
        sess_uuid = uuid.UUID(session_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid session ID format: '{session_id}'",
        )

    sess = db.query(SessionModel).filter(SessionModel.id == sess_uuid).first()
    if not sess or sess.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    if not sess.revoked_at:
        sess.revoked_at = datetime.now(timezone.utc)
        db.commit()

    response = JSONResponse(content={"status": "session_revoked", "id": str(sess.id)})
    if sess.id == current_session.id:
        response.delete_cookie(key="session_token", path="/")

    return response

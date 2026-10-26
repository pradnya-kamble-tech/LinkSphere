import logging

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    clear_session_cookie,
    create_session,
    get_current_user,
    revoke_session,
    set_session_cookie,
)
from app.db.session import get_db
from app.models.user import User
from app.services.auth import (
    EmailDeliveryError,
    request_email_login,
    verify_email_login_token,
)
from app.services.registration import (
    request_registration_verification,
    verify_registration_email,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="A URL shortener and link analytics platform.",
    version=settings.app_version,
)


class EmailLoginRequest(BaseModel):
    email: EmailStr


class EmailLoginVerification(BaseModel):
    token: str


@app.get("/")
def read_root():
    return {
        "message": "Welcome to LinkSphere API!",
        "status": "running",
        "environment": settings.environment,
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "linksphere-api",
        "environment": settings.environment,
    }


@app.post("/auth/register", status_code=status.HTTP_202_ACCEPTED)
def register(
    payload: EmailLoginRequest,
    db: Session = Depends(get_db),
):
    """Request email ownership verification for registration."""
    try:
        request_registration_verification(db, str(payload.email))
    except EmailDeliveryError:
        logger.exception("Registration verification email delivery failed")

    return {
        "message": (
            "If this address can be registered, "
            "a verification email will be sent."
        )
    }


@app.post("/auth/register/verify")
def verify_registration(
    payload: EmailLoginVerification,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify email ownership, create the account, and start a session."""
    user = verify_registration_email(db, payload.token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification link is invalid, expired, or already used.",
        )

    raw_token, _ = create_session(db, user.id)
    set_session_cookie(response, raw_token)

    return {
        "message": "Email verified and account created successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "email_verified": user.email_verified_at is not None,
        },
    }


@app.post("/auth/email/request", status_code=status.HTTP_202_ACCEPTED)
def request_email_sign_in(
    payload: EmailLoginRequest,
    db: Session = Depends(get_db),
):
    """Request a sign-in link without revealing account existence."""
    try:
        request_email_login(db, str(payload.email))
    except EmailDeliveryError:
        logger.exception("Sign-in email delivery failed")

    return {
        "message": (
            "If this address belongs to an eligible account, "
            "a sign-in link will be sent."
        )
    }


@app.post("/auth/email/verify")
def verify_email_sign_in(
    payload: EmailLoginVerification,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a one-time email token and create a session."""
    user = verify_email_login_token(db, payload.token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The sign-in link is invalid, expired, or already used.",
        )

    raw_token, _ = create_session(db, user.id)
    set_session_cookie(response, raw_token)

    return {
        "message": "Signed in successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "email_verified": user.email_verified_at is not None,
        },
    }


@app.post("/auth/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(
        default=None,
        alias=settings.session_cookie_name,
    ),
):
    """Revoke the current session and clear the browser cookie."""
    if session_token:
        revoke_session(db, session_token)

    clear_session_cookie(response)
    return {"message": "Logged out successfully"}


@app.get("/auth/me")
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's public details."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "email_verified": current_user.email_verified_at is not None,
    }

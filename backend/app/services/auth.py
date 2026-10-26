
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import resend
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_login_token import EmailLoginToken
from app.models.user import User


class EmailDeliveryError(Exception):
    """Raised when the email provider cannot deliver a login message."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_magic_link(email: str, token: str, purpose: str = "login") -> None:
    if not settings.resend_api_key:
        raise EmailDeliveryError("Email delivery is not configured.")

    params = {
        "token": token,
    }
    if purpose not in {"login", "registration"}:
        raise ValueError("Unsupported email purpose.")

    route = "/auth/register/verify" if purpose == "registration" else "/auth/verify"
    action = "verify your email address" if purpose == "registration" else "sign in to LinkSphere"
    link_text = "Verify email address" if purpose == "registration" else "Sign in to LinkSphere"
    subject = "Verify your LinkSphere email" if purpose == "registration" else "Your LinkSphere sign-in link"

    login_url = (
        f"{settings.frontend_url.rstrip('/')}{route}?"
        f"{urlencode(params)}"
    )

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [email],
                "subject": subject,
                "html": (
                    f"<p>Use the link below to {action}.</p>"
                    f'<p><a href="{login_url}">{link_text}</a></p>'
                    f"<p>This link expires in {settings.email_verification_token_expire_minutes if purpose == 'registration' else settings.email_login_token_expire_minutes} minutes and can only be used once.</p>"
                    "<p>If you did not request this email, you can ignore it.</p>"
                ),
            }
        )
    except Exception as exc:
        raise EmailDeliveryError("Unable to send the sign-in email.") from exc


def request_email_login(db: Session, email: str) -> None:
    """Request a sign-in link without disclosing account existence."""
    normalized_email = email.strip().lower()

    user = db.scalar(
        select(User).where(User.email == normalized_email)
    )

    # Do not create accounts until email ownership is verified.
    # Existing accounts must have a verified address before login.
    if user is None or user.email_verified_at is None:
        return

    now = datetime.now(timezone.utc)

    # Invalidate outstanding, unused login links for this account.
    db.execute(
        update(EmailLoginToken)
        .where(
            EmailLoginToken.user_id == user.id,
            EmailLoginToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = secrets.token_urlsafe(32)
    token_record = EmailLoginToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(
            minutes=settings.email_login_token_expire_minutes
        ),
    )

    db.add(token_record)
    db.commit()

    try:
        _send_magic_link(normalized_email, raw_token)
    except EmailDeliveryError:
        # Invalidate the token if the provider rejects the send request.
        db.execute(
            update(EmailLoginToken)
            .where(EmailLoginToken.id == token_record.id)
            .values(used_at=datetime.now(timezone.utc))
        )
        db.commit()
        raise



def verify_email_login_token(db: Session, raw_token: str) -> User | None:
    """Consume a valid login token exactly once and return its user."""
    if not raw_token or len(raw_token) > 200:
        return None

    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    # The conditional UPDATE makes token consumption atomic:
    # concurrent requests cannot both consume the same token.
    result = db.execute(
        update(EmailLoginToken)
        .where(
            EmailLoginToken.token_hash == token_hash,
            EmailLoginToken.used_at.is_(None),
            EmailLoginToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(EmailLoginToken.user_id)
    )

    user_id = result.scalar_one_or_none()

    if user_id is None:
        db.rollback()
        return None

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.email_verified_at.is_not(None),
        )
    )

    if user is None:
        db.rollback()
        return None

    db.commit()
    return user

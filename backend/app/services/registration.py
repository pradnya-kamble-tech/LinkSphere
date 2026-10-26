import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.services.auth import EmailDeliveryError, _send_magic_link


def _hash_verification_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_registration_verification(db: Session, email: str) -> None:
    normalized_email = email.strip().lower()

    existing_user = db.scalar(
        select(User).where(User.email == normalized_email)
    )
    if existing_user is not None and existing_user.email_verified_at is not None:
        return

    now = datetime.now(timezone.utc)

    db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.email == normalized_email,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = secrets.token_urlsafe(32)
    record = EmailVerificationToken(
        email=normalized_email,
        token_hash=_hash_verification_token(raw_token),
        expires_at=now + timedelta(
            minutes=settings.email_verification_token_expire_minutes
        ),
    )
    db.add(record)
    db.commit()

    try:
        _send_magic_link(normalized_email, raw_token, purpose="registration")
    except EmailDeliveryError:
        db.execute(
            update(EmailVerificationToken)
            .where(EmailVerificationToken.id == record.id)
            .values(used_at=datetime.now(timezone.utc))
        )
        db.commit()
        raise


def verify_registration_email(db: Session, raw_token: str) -> User | None:
    if not raw_token or len(raw_token) > 200:
        return None

    now = datetime.now(timezone.utc)
    result = db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash
            == _hash_verification_token(raw_token),
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(EmailVerificationToken.email)
    )
    email = result.scalar_one_or_none()

    if email is None:
        db.rollback()
        return None

    user = db.scalar(select(User).where(User.email == email))

    if user is not None and user.email_verified_at is not None:
        db.rollback()
        return None

    if user is None:
        user = User(email=email, email_verified_at=now)
        db.add(user)
    else:
        user.email_verified_at = now

    db.commit()
    db.refresh(user)
    return user

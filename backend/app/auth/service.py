import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import generate_session_token, hash_session_token
from app.users.models import User
from app.auth.models import AuthIdentity, Session


def find_or_create_user_and_identity(
    db: DBSession,
    provider: str,
    provider_user_id: str,
    email: str,
    email_verified: bool,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> User:
    """Find or create user and link identity inside a single transaction with savepoint race handling."""
    normalized_email = email.strip().lower()

    # 1. Check if identity already exists
    identity = db.query(AuthIdentity).filter_by(
        provider=provider, provider_user_id=provider_user_id
    ).first()
    if identity:
        return identity.user

    # 2. Check if user with this verified email already exists
    existing_user = db.query(User).filter_by(email=normalized_email).first()

    if existing_user:
        # Link identity to existing user (only if verified)
        if not email_verified:
            raise ValueError("Refusing to link unverified email")

        try:
            with db.begin_nested():
                identity = AuthIdentity(
                    user_id=existing_user.id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    email_verified=email_verified,
                )
                db.add(identity)
                db.flush()
            db.commit()
            return existing_user
        except IntegrityError:
            db.rollback()
            # Concurrently linked; retry lookup
            identity = db.query(AuthIdentity).filter_by(
                provider=provider, provider_user_id=provider_user_id
            ).one()
            return identity.user

    # 3. User does not exist: create user and identity
    try:
        with db.begin_nested():
            new_user = User(
                email=normalized_email,
                name=name,
                avatar_url=avatar_url,
            )
            db.add(new_user)
            db.flush()

            identity = AuthIdentity(
                user_id=new_user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                email_verified=email_verified,
            )
            db.add(identity)
            db.flush()
        db.commit()
        return new_user
    except IntegrityError:
        db.rollback()
        # Concurrent registration with same email occurred; resolve user and link
        user = db.query(User).filter_by(email=normalized_email).first()
        if user:
            existing_identity = db.query(AuthIdentity).filter_by(
                provider=provider, provider_user_id=provider_user_id
            ).first()
            if not existing_identity:
                try:
                    with db.begin_nested():
                        identity = AuthIdentity(
                            user_id=user.id,
                            provider=provider,
                            provider_user_id=provider_user_id,
                            email_verified=email_verified,
                        )
                        db.add(identity)
                        db.flush()
                    db.commit()
                except IntegrityError:
                    db.rollback()
            return user
        raise


def create_user_session(db: DBSession, user_id: uuid.UUID) -> Tuple[str, Session]:
    """Generate secure session token, persist its SHA-256 hash, and return (raw_token, session)."""
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.SESSION_LIFETIME_DAYS)

    session = Session(
        user_id=user_id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        last_seen_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def get_valid_session(db: DBSession, raw_token: Optional[str]) -> Optional[Tuple[Session, User]]:
    """Validate raw token against stored token_hash. Updates last_seen_at if older than 5 minutes."""
    if not raw_token:
        return None

    token_hash = hash_session_token(raw_token)
    session = (
        db.query(Session)
        .filter(Session.token_hash == token_hash, Session.revoked_at.is_(None))
        .first()
    )
    if not session:
        return None

    now = datetime.now(timezone.utc)

    # Expiry checks
    if session.expires_at <= now:
        return None

    if session.last_seen_at and (
        now - session.last_seen_at > timedelta(hours=settings.SESSION_IDLE_TIMEOUT_HOURS)
    ):
        return None

    # Amendment 5: Update last_seen_at only if stored value is older than 5 minutes
    if not session.last_seen_at or (now - session.last_seen_at > timedelta(minutes=5)):
        session.last_seen_at = now
        db.commit()

    return session, session.user


def revoke_session(db: DBSession, raw_token: Optional[str]) -> bool:
    """Revoke session by token_hash."""
    if not raw_token:
        return False
    token_hash = hash_session_token(raw_token)
    session = db.query(Session).filter_by(token_hash=token_hash).first()
    if session and not session.revoked_at:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False

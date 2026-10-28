import hashlib
import secrets
from typing import Any, Dict, Optional
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.core.config import settings

state_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="linksphere-oauth-state")

ALLOWLISTED_NEXT_PATHS = {"/", "/dashboard"}


def hash_session_token(token: str) -> str:
    """Compute SHA-256 hash of raw session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    """Generate a cryptographically secure random session token >= 32 bytes."""
    return secrets.token_urlsafe(32)


def generate_random_string(length: int = 32) -> str:
    """Generate a secure hex string for state and nonce."""
    return secrets.token_hex(length)


def validate_next_path(target: Optional[str]) -> str:
    """Ensure target path is strictly in the internal allowlist ('/' or '/dashboard')."""
    if target and target in ALLOWLISTED_NEXT_PATHS:
        return target
    return "/dashboard"


def create_signed_oauth_state(payload: Dict[str, Any]) -> str:
    """Sign OAuth state payload with secret key."""
    return state_serializer.dumps(payload)


def verify_signed_oauth_state(token: str, max_age: int = 600) -> Optional[Dict[str, Any]]:
    """Verify and decode signed state payload within max_age (default 10 min)."""
    try:
        data = state_serializer.loads(token, max_age=max_age)
        if isinstance(data, dict):
            return data
        return None
    except (BadSignature, SignatureExpired):
        return None


def is_valid_origin(origin: Optional[str]) -> bool:
    """Validate request Origin header against configured FRONTEND_ORIGIN."""
    return bool(origin and origin == settings.FRONTEND_ORIGIN)

import re
import ipaddress
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.core.config import settings

RESERVED_CODES = {
    "api",
    "docs",
    "redoc",
    "openapi.json",
    "health",
    "login",
    "signup",
    "dashboard",
    "assets",
    "static",
    "favicon.ico",
    "robots.txt",
    "sitemap.xml",
    "admin",
}

CUSTOM_CODE_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,30}$")


def validate_url_string(url: str) -> str:
    """Validate destination URL per Phase 4 requirements."""
    if not isinstance(url, str):
        raise ValueError("URL must be a string")

    cleaned = url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty")
    if len(cleaned) > 2048:
        raise ValueError("URL exceeds maximum length of 2048 characters")

    # Reject control characters (0-31 and 127)
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("URL contains illegal control characters")

    parsed = urllib.parse.urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("Only http and https URL schemes are permitted")

    if not parsed.netloc:
        raise ValueError("URL missing valid host")

    # Reject embedded user credentials (user:pass@)
    if parsed.username or parsed.password or "@" in (parsed.netloc.split(":")[0] if parsed.netloc else ""):
        raise ValueError("URL credentials are not permitted")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL hostname")

    # Reject redirect loops: destination host matches short-link host
    short_link_parsed = urllib.parse.urlsplit(settings.SHORT_LINK_BASE_URL)
    if short_link_parsed.hostname and hostname.lower() == short_link_parsed.hostname.lower():
        raise ValueError("Redirect loop detected: destination cannot be the short-link host")

    # Reject localhost / private range unless environment is local or test
    is_local_env = settings.ENVIRONMENT.lower() in ("local", "test")
    if not is_local_env:
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise ValueError("Localhost destinations are not permitted in production")

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise ValueError("Private network destinations are not permitted in production")
        except ValueError:
            # Not an IP literal, standard domain name
            pass

    return cleaned


class LinkCreate(BaseModel):
    original_url: str
    custom_code: Optional[str] = None
    expires_at: Optional[datetime] = None

    @field_validator("original_url")
    @classmethod
    def validate_original_url(cls, v: str) -> str:
        return validate_url_string(v)

    @field_validator("custom_code")
    @classmethod
    def validate_custom_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        if trimmed.lower() in RESERVED_CODES:
            raise ValueError(f"'{trimmed}' is a reserved system code and cannot be used")
        if not CUSTOM_CODE_REGEX.match(trimmed):
            raise ValueError(
                "Custom short code must be 3-30 characters and contain only letters, numbers, underscores, or hyphens"
            )
        return trimmed

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        utc_dt = v.astimezone(timezone.utc)
        if utc_dt <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return utc_dt


class LinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        utc_dt = v.astimezone(timezone.utc)
        if utc_dt <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return utc_dt


class LinkRead(BaseModel):
    id: int
    short_code: str
    short_url: str
    original_url: str
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime
    click_count: int = 0


class LinkListResponse(BaseModel):
    items: List[LinkRead]
    total: int
    limit: int
    offset: int

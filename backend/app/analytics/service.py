import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from app.core.db import SessionLocal
import app.users.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.links.models  # noqa: F401
import app.analytics.models  # noqa: F401
from app.analytics.models import ClickEvent

logger = logging.getLogger(__name__)


def parse_device_type(user_agent: Optional[str]) -> str:
    """
    Hand-written rule-based device classifier without external dependencies.
    Categorizes into: bot, tablet, mobile, desktop, unknown.
    Never stores or returns raw user-agent strings.
    """
    if not user_agent or not isinstance(user_agent, str):
        return "unknown"

    ua = user_agent.lower()

    # 1. Bots and automated crawlers
    bot_indicators = (
        "bot",
        "spider",
        "crawl",
        "slurp",
        "curl",
        "wget",
        "python",
        "urllib",
        "httpclient",
        "postman",
        "locust",
    )
    if any(b in ua for b in bot_indicators):
        return "bot"

    # 2. Tablets (checked before generic mobile)
    tablet_indicators = ("ipad", "tablet", "playbook", "silk")
    if any(t in ua for t in tablet_indicators):
        return "tablet"

    # 3. Mobile phones
    mobile_indicators = ("mobi", "iphone", "android", "webos", "blackberry")
    if any(m in ua for m in mobile_indicators):
        return "mobile"

    # 4. Desktops / Laptops
    desktop_indicators = ("windows", "macintosh", "linux", "x11", "cros")
    if any(d in ua for d in desktop_indicators):
        return "desktop"

    return "unknown"


def sanitize_referrer(referrer: Optional[str]) -> Optional[str]:
    """
    Sanitize Referer header to scheme + host only.
    Truncates to 512 characters. Never stores path, query string, or fragments.
    """
    if not referrer or not isinstance(referrer, str):
        return None

    cleaned = referrer.strip()
    if not cleaned:
        return None

    try:
        parsed = urllib.parse.urlsplit(cleaned)
        if parsed.scheme and parsed.netloc:
            sanitized = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            return sanitized[:512]
    except Exception:
        pass

    return None


def record_click_background(
    link_id: int,
    referrer: Optional[str],
    user_agent: Optional[str],
) -> None:
    """
    Record a click event in a background task using an independent DB session.
    Failures are safely logged without exposing secrets or full destination URLs.
    """
    device_type = parse_device_type(user_agent)
    clean_ref = sanitize_referrer(referrer)

    import app.core.db
    db = app.core.db.SessionLocal()
    try:
        click = ClickEvent(
            link_id=link_id,
            clicked_at=datetime.now(timezone.utc),
            referrer=clean_ref,
            device_type=device_type,
            country=None,  # Stays NULL per Phase 4 specification
        )
        db.add(click)
        db.commit()
    except Exception as exc:
        db.rollback()
        # Log failure safely without exposing sensitive data
        logger.warning(
            "Failed to record click event for link_id=%s: %s",
            link_id,
            exc.__class__.__name__,
        )
    finally:
        db.close()

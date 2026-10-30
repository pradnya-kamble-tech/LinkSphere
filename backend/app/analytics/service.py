import logging
import urllib.parse
import zoneinfo
import re
from datetime import datetime, timezone, timedelta, time
from typing import Optional, List, Dict, Any, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
import app.users.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.links.models  # noqa: F401
from app.links.models import Link
import app.analytics.models  # noqa: F401
from app.analytics.models import ClickEvent
from app.links.service import build_short_url

logger = logging.getLogger(__name__)


# =========================================================================
# 1. CLICK EVENT RECORDING & NORMALIZATION (BACKGROUND TASKS)
# =========================================================================

def parse_device_type(user_agent: Optional[str]) -> str:
    """
    Categorizes User-Agent into: bot, tablet, mobile, desktop, unknown.
    Never stores or returns raw user-agent strings.
    """
    if not user_agent or not isinstance(user_agent, str):
        return "unknown"

    ua = user_agent.lower()
    bot_indicators = (
        "bot", "spider", "crawl", "slurp", "curl", "wget", "python",
        "urllib", "httpclient", "postman", "locust"
    )
    if any(b in ua for b in bot_indicators):
        return "bot"

    tablet_indicators = ("ipad", "tablet", "playbook", "silk")
    if any(t in ua for t in tablet_indicators):
        return "tablet"

    mobile_indicators = ("mobi", "iphone", "android", "webos", "blackberry")
    if any(m in ua for m in mobile_indicators):
        return "mobile"

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
    """Record click event in background using an independent DB session."""
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
            country=None,
        )
        db.add(click)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Failed to record click event for link_id=%s: %s",
            link_id,
            exc.__class__.__name__,
        )
    finally:
        db.close()


# =========================================================================
# 2. TIMEZONE & RANGE BOUNDARIES HELPER (AMENDMENTS 1 & 2)
# =========================================================================

def validate_tz(tz_name: str) -> zoneinfo.ZoneInfo:
    """Validate IANA timezone name. Returns ZoneInfo or raises 422."""
    if not tz_name or not isinstance(tz_name, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Timezone must be a non-empty string",
        )
    try:
        return zoneinfo.ZoneInfo(tz_name.strip())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid or unrecognized IANA timezone: '{tz_name}'",
        )


def calculate_range_boundaries(
    range_days: int,
    tz_name: str,
    as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Computes local calendar day boundaries converted to UTC.
    Range = last N calendar days INCLUDING today, from local midnight of (today - (N-1)) to now_utc.
    Previous period = the N calendar days immediately before.
    DST-safe via zoneinfo local midnight conversion.
    """
    if range_days not in (7, 30, 90):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid range: {range_days}. Allowed values are 7, 30, or 90.",
        )

    tz = validate_tz(tz_name)
    now_utc = as_of if as_of is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_local = now_utc.astimezone(tz)
    today_local = now_local.date()

    start_day = today_local - timedelta(days=range_days - 1)
    
    # Generate continuous list of local days
    day_ranges: List[Tuple[datetime.date, datetime, datetime]] = []
    for i in range(range_days):
        d = start_day + timedelta(days=i)
        d_start_local = datetime.combine(d, time.min, tzinfo=tz)
        d_end_local = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
        d_start_utc = d_start_local.astimezone(timezone.utc)
        d_end_utc = d_end_local.astimezone(timezone.utc)
        day_ranges.append((d, d_start_utc, d_end_utc))

    current_start_utc = day_ranges[0][1]
    current_end_utc = now_utc

    # Previous equal-length period: N days prior
    prev_start_day = start_day - timedelta(days=range_days)
    prev_start_local = datetime.combine(prev_start_day, time.min, tzinfo=tz)
    prev_start_utc = prev_start_local.astimezone(timezone.utc)
    prev_end_utc = current_start_utc

    return {
        "range_days": range_days,
        "tz": tz_name,
        "resolved_start_date": start_day.isoformat(),
        "resolved_end_date": today_local.isoformat(),
        "current_start_utc": current_start_utc,
        "current_end_utc": current_end_utc,
        "prev_start_utc": prev_start_utc,
        "prev_end_utc": prev_end_utc,
        "day_ranges": day_ranges,
    }


def build_binary_case(ranges: List[Tuple[datetime.date, datetime, datetime]]) -> str:
    """Builds a balanced binary search CASE statement for O(log N) bucketing in SQL."""
    if len(ranges) == 1:
        return f"'{ranges[0][0].isoformat()}'::date"
    mid = len(ranges) // 2
    split_utc = ranges[mid][1].isoformat()
    left = build_binary_case(ranges[:mid])
    right = build_binary_case(ranges[mid:])
    return f"CASE WHEN c.clicked_at < '{split_utc}' THEN {left} ELSE {right} END"


# =========================================================================
# 3. OWNERSHIP VERIFICATION & CONDITIONAL QUERIES (AMENDMENT 3)
# =========================================================================

def verify_link_ownership(db: Session, user_id: uuid.UUID, link_id: int) -> Link:
    """Ensure link exists, belongs to user, and is not soft-deleted."""
    if not isinstance(link_id, int) or link_id < 1 or link_id > 2147483647:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid link_id: {link_id}",
        )
    link = db.execute(
        select(Link).where(
            Link.id == link_id,
            Link.user_id == user_id,
            Link.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Link {link_id} not found",
        )
    return link


# =========================================================================
# 4. ANALYTICS QUERIES (SUMMARY, TIMESERIES, TOP-LINKS, BREAKDOWN)
# =========================================================================

def get_analytics_summary(
    db: Session,
    user_id: uuid.UUID,
    range_days: int,
    tz_name: str,
    link_id: Optional[int] = None,
) -> Dict[str, Any]:
    bounds = calculate_range_boundaries(range_days, tz_name)

    cur_start = bounds["current_start_utc"]
    cur_end = bounds["current_end_utc"]
    prev_start = bounds["prev_start_utc"]
    prev_end = bounds["prev_end_utc"]

    if link_id is not None:
        verify_link_ownership(db, user_id, link_id)
        # Dedicated query shape for single link (uses index-only scan)
        stmt = text("""
            SELECT
              count(CASE WHEN c.clicked_at >= :cur_start AND c.clicked_at <= :cur_end THEN 1 END) AS current_clicks,
              count(CASE WHEN c.clicked_at >= :prev_start AND c.clicked_at < :prev_end THEN 1 END) AS previous_clicks
            FROM click_events c
            WHERE c.link_id = :link_id
              AND c.clicked_at >= :prev_start
              AND c.clicked_at <= :cur_end;
        """)
        row = db.execute(stmt, {
            "link_id": link_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
            "prev_start": prev_start,
            "prev_end": prev_end,
        }).first()
    else:
        # Multi-link query shape
        stmt = text("""
            SELECT
              count(CASE WHEN c.clicked_at >= :cur_start AND c.clicked_at <= :cur_end THEN 1 END) AS current_clicks,
              count(CASE WHEN c.clicked_at >= :prev_start AND c.clicked_at < :prev_end THEN 1 END) AS previous_clicks
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :prev_start
              AND c.clicked_at <= :cur_end;
        """)
        row = db.execute(stmt, {
            "user_id": user_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
            "prev_start": prev_start,
            "prev_end": prev_end,
        }).first()

    current_clicks = int(row.current_clicks) if row and row.current_clicks else 0
    previous_clicks = int(row.previous_clicks) if row and row.previous_clicks else 0

    if previous_clicks == 0:
        percent_change = None
    else:
        percent_change = round(((current_clicks - previous_clicks) / previous_clicks) * 100.0, 1)

    return {
        "current_clicks": current_clicks,
        "previous_clicks": previous_clicks,
        "percent_change": percent_change,
        "resolved_start_date": bounds["resolved_start_date"],
        "resolved_end_date": bounds["resolved_end_date"],
        "tz": bounds["tz"],
        "link_id": link_id,
    }


def get_analytics_timeseries(
    db: Session,
    user_id: uuid.UUID,
    range_days: int,
    tz_name: str,
    link_id: Optional[int] = None,
) -> Dict[str, Any]:
    bounds = calculate_range_boundaries(range_days, tz_name)
    day_ranges = bounds["day_ranges"]
    binary_case_expr = build_binary_case(day_ranges)

    cur_start = bounds["current_start_utc"]
    cur_end = bounds["current_end_utc"]

    if link_id is not None:
        verify_link_ownership(db, user_id, link_id)
        stmt = text(f"""
            SELECT
              {binary_case_expr} AS day,
              count(c.id) AS click_count
            FROM click_events c
            WHERE c.link_id = :link_id
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY 1 ASC;
        """)
        rows = db.execute(stmt, {
            "link_id": link_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
        }).all()
    else:
        stmt = text(f"""
            SELECT
              {binary_case_expr} AS day,
              count(c.id) AS click_count
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY 1 ASC;
        """)
        rows = db.execute(stmt, {
            "user_id": user_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
        }).all()

    # Zero-filling dictionary initialization
    counts_by_date = {d.isoformat(): 0 for d, _, _ in day_ranges}
    for r in rows:
        day_str = str(r.day)
        if day_str in counts_by_date:
            counts_by_date[day_str] = int(r.click_count)

    items = [{"date": d_str, "click_count": counts_by_date[d_str]} for d, _, _ in day_ranges for d_str in [d.isoformat()]]

    return {
        "items": items,
        "resolved_start_date": bounds["resolved_start_date"],
        "resolved_end_date": bounds["resolved_end_date"],
        "tz": bounds["tz"],
        "link_id": link_id,
    }


def get_analytics_top_links(
    db: Session,
    user_id: uuid.UUID,
    range_days: int,
    tz_name: str,
    limit: int = 10,
) -> Dict[str, Any]:
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Limit must be between 1 and 50",
        )

    bounds = calculate_range_boundaries(range_days, tz_name)
    cur_start = bounds["current_start_utc"]
    cur_end = bounds["current_end_utc"]

    stmt = text("""
        SELECT
          l.id,
          l.short_code,
          l.original_url,
          count(c.id) AS click_count
        FROM links l
        JOIN click_events c ON l.id = c.link_id
        WHERE l.user_id = :user_id
          AND l.deleted_at IS NULL
          AND c.clicked_at >= :cur_start
          AND c.clicked_at <= :cur_end
        GROUP BY l.id, l.short_code, l.original_url
        ORDER BY click_count DESC, l.id ASC
        LIMIT :limit;
    """)
    rows = db.execute(stmt, {
        "user_id": user_id,
        "cur_start": cur_start,
        "cur_end": cur_end,
        "limit": limit,
    }).all()

    items = [
        {
            "id": r.id,
            "short_code": r.short_code,
            "short_url": build_short_url(r.short_code),
            "original_url": r.original_url,
            "click_count": int(r.click_count),
        }
        for r in rows
    ]

    return {
        "items": items,
        "resolved_start_date": bounds["resolved_start_date"],
        "resolved_end_date": bounds["resolved_end_date"],
        "tz": bounds["tz"],
    }


def get_analytics_breakdown(
    db: Session,
    user_id: uuid.UUID,
    range_days: int,
    tz_name: str,
    link_id: Optional[int] = None,
) -> Dict[str, Any]:
    bounds = calculate_range_boundaries(range_days, tz_name)
    cur_start = bounds["current_start_utc"]
    cur_end = bounds["current_end_utc"]

    # Referrers & Devices aggregated in a single database pass via GROUPING SETS
    if link_id is not None:
        verify_link_ownership(db, user_id, link_id)
        stmt = text("""
            SELECT
              grouping(host_ref) AS grp_host,
              grouping(dev_type) AS grp_dev,
              host_ref,
              dev_type,
              count(*) AS click_count
            FROM (
              SELECT
                CASE
                  WHEN c.referrer IS NULL OR trim(c.referrer) = '' THEN 'Direct'
                  ELSE split_part(regexp_replace(c.referrer, '^https?://', '', 'i'), '/', 1)
                END AS host_ref,
                coalesce(c.device_type, 'unknown') AS dev_type
              FROM click_events c
              WHERE c.link_id = :link_id
                AND c.clicked_at >= :cur_start
                AND c.clicked_at <= :cur_end
            ) sub
            GROUP BY GROUPING SETS ((host_ref), (dev_type));
        """)
        rows = db.execute(stmt, {
            "link_id": link_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
        }).all()
    else:
        stmt = text("""
            SELECT
              grouping(host_ref) AS grp_host,
              grouping(dev_type) AS grp_dev,
              host_ref,
              dev_type,
              count(*) AS click_count
            FROM (
              SELECT
                CASE
                  WHEN c.referrer IS NULL OR trim(c.referrer) = '' THEN 'Direct'
                  ELSE split_part(regexp_replace(c.referrer, '^https?://', '', 'i'), '/', 1)
                END AS host_ref,
                coalesce(c.device_type, 'unknown') AS dev_type
              FROM click_events c
              JOIN links l ON c.link_id = l.id
              WHERE l.user_id = :user_id
                AND l.deleted_at IS NULL
                AND c.clicked_at >= :cur_start
                AND c.clicked_at <= :cur_end
            ) sub
            GROUP BY GROUPING SETS ((host_ref), (dev_type));
        """)
        rows = db.execute(stmt, {
            "user_id": user_id,
            "cur_start": cur_start,
            "cur_end": cur_end,
        }).all()

    ref_rows = [r for r in rows if r.grp_host == 0]
    dev_rows = [r for r in rows if r.grp_dev == 0]

    total_clicks = sum(int(r.click_count) for r in ref_rows)

    # Process referrers: Top 10 + "Direct" + "Other"
    direct_count = 0
    non_direct_items = []
    for r in ref_rows:
        host = r.host_ref
        cnt = int(r.click_count)
        if host.lower() == "direct":
            direct_count += cnt
        else:
            non_direct_items.append((host, cnt))

    # Top 10 non-direct
    top_10_non_direct = non_direct_items[:10]
    other_non_direct = non_direct_items[10:]
    other_count = sum(cnt for _, cnt in other_non_direct)

    referrers_list = []
    for host, cnt in top_10_non_direct:
        pct = round((cnt / total_clicks) * 100.0, 1) if total_clicks > 0 else 0.0
        referrers_list.append({"name": host, "click_count": cnt, "percentage": pct})

    if other_count > 0:
        pct = round((other_count / total_clicks) * 100.0, 1) if total_clicks > 0 else 0.0
        referrers_list.append({"name": "Other", "click_count": other_count, "percentage": pct})

    if direct_count > 0:
        pct = round((direct_count / total_clicks) * 100.0, 1) if total_clicks > 0 else 0.0
        referrers_list.append({"name": "Direct", "click_count": direct_count, "percentage": pct})

    # Sort referrers deterministically: count DESC, then name ASC
    referrers_list.sort(key=lambda x: (-x["click_count"], x["name"]))

    # Process devices
    devices_list = []
    for r in dev_rows:
        cnt = int(r.click_count)
        pct = round((cnt / total_clicks) * 100.0, 1) if total_clicks > 0 else 0.0
        devices_list.append({
            "name": r.dev_type,
            "click_count": cnt,
            "percentage": pct,
        })
    devices_list.sort(key=lambda x: (-x["click_count"], x["name"]))

    return {
        "referrers": referrers_list,
        "devices": devices_list,
        "total_clicks": total_clicks,
        "resolved_start_date": bounds["resolved_start_date"],
        "resolved_end_date": bounds["resolved_end_date"],
        "tz": bounds["tz"],
        "link_id": link_id,
    }

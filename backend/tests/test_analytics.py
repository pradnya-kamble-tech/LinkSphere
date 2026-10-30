import uuid
from datetime import datetime, timezone, timedelta, date, time
import zoneinfo
import pytest
import httpx

from app.core.config import settings
from app.users.models import User
from app.auth.service import create_user_session
from app.links.models import Link
from app.analytics.models import ClickEvent
from app.analytics.service import calculate_range_boundaries, validate_tz


@pytest.fixture
def auth_user(db):
    user = User(email="analytics_owner@example.com", name="Analytics Owner")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token


@pytest.fixture
def other_user(db):
    user = User(email="analytics_other@example.com", name="Other Owner")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token


# =========================================================================
# 1. DST BOUNDARIES & ZONEINFO TESTS (AMENDMENT 1 & 2)
# =========================================================================

def test_dst_spring_forward_2026_03_08():
    """America/New_York on 2026-03-08 has 23 hours."""
    as_of = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
    bounds = calculate_range_boundaries(range_days=7, tz_name="America/New_York", as_of=as_of)
    
    # Locate the day range for 2026-03-08
    march_8_entry = [r for r in bounds["day_ranges"] if r[0] == date(2026, 3, 8)][0]
    d, start_utc, end_utc = march_8_entry
    duration_hours = (end_utc - start_utc).total_seconds() / 3600.0
    assert duration_hours == 23.0
    # EST is UTC-5 before 2:00 AM, EDT is UTC-4 after 3:00 AM
    assert start_utc == datetime(2026, 3, 8, 5, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 3, 9, 4, 0, 0, tzinfo=timezone.utc)


def test_dst_fall_back_2026_11_01():
    """America/New_York on 2026-11-01 has 25 hours."""
    as_of = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    bounds = calculate_range_boundaries(range_days=7, tz_name="America/New_York", as_of=as_of)
    
    # Locate the day range for 2026-11-01
    nov_1_entry = [r for r in bounds["day_ranges"] if r[0] == date(2026, 11, 1)][0]
    d, start_utc, end_utc = nov_1_entry
    duration_hours = (end_utc - start_utc).total_seconds() / 3600.0
    assert duration_hours == 25.0
    # EDT is UTC-4 before 2:00 AM, EST is UTC-5 after 2:00 AM
    assert start_utc == datetime(2026, 11, 1, 4, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 11, 2, 5, 0, 0, tzinfo=timezone.utc)


def test_range_boundaries_structure():
    bounds = calculate_range_boundaries(range_days=30, tz_name="UTC")
    assert len(bounds["day_ranges"]) == 30
    assert bounds["range_days"] == 30
    assert bounds["tz"] == "UTC"
    assert bounds["current_start_utc"] == bounds["day_ranges"][0][1]


# =========================================================================
# 2. AUTHENTICATION GATES
# =========================================================================

@pytest.mark.anyio
async def test_analytics_endpoints_require_auth(async_client: httpx.AsyncClient):
    endpoints = [
        "/api/analytics/summary",
        "/api/analytics/timeseries",
        "/api/analytics/top-links",
        "/api/analytics/breakdown",
    ]
    for ep in endpoints:
        resp = await async_client.get(ep)
        assert resp.status_code == 401, f"{ep} did not require authentication"


# =========================================================================
# 3. EMPTY STATE TESTS
# =========================================================================

@pytest.mark.anyio
async def test_analytics_empty_states(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    # 1. Summary empty state
    s_resp = await async_client.get("/api/analytics/summary?range=30&tz=UTC")
    assert s_resp.status_code == 200
    s_data = s_resp.json()
    assert s_data["current_clicks"] == 0
    assert s_data["previous_clicks"] == 0
    assert s_data["percent_change"] is None

    # 2. Timeseries empty state (zero-filled)
    t_resp = await async_client.get("/api/analytics/timeseries?range=7&tz=UTC")
    assert t_resp.status_code == 200
    t_data = t_resp.json()
    assert len(t_data["items"]) == 7
    for item in t_data["items"]:
        assert item["click_count"] == 0

    # 3. Top links empty state
    l_resp = await async_client.get("/api/analytics/top-links?range=30&tz=UTC")
    assert l_resp.status_code == 200
    l_data = l_resp.json()
    assert l_data["items"] == []

    # 4. Breakdown empty state
    b_resp = await async_client.get("/api/analytics/breakdown?range=30&tz=UTC")
    assert b_resp.status_code == 200
    b_data = b_resp.json()
    assert b_data["total_clicks"] == 0
    assert b_data["referrers"] == []
    assert b_data["devices"] == []


# =========================================================================
# 4. SUMMARY & PERCENT CHANGE MATH
# =========================================================================

@pytest.mark.anyio
async def test_analytics_summary_percent_change(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    link = Link(user_id=user.id, short_code="sumtest", original_url="https://example.com/target")
    db.add(link)
    db.commit()

    now = datetime.now(timezone.utc)
    # Add 10 clicks in current period (today)
    for _ in range(10):
        db.add(ClickEvent(link_id=link.id, clicked_at=now, referrer="https://google.com", device_type="desktop"))

    # Add 5 clicks in previous period (e.g. 10 days ago for a 7-day range)
    ten_days_ago = now - timedelta(days=10)
    for _ in range(5):
        db.add(ClickEvent(link_id=link.id, clicked_at=ten_days_ago, referrer="https://google.com", device_type="desktop"))
    db.commit()

    # Query with range=7
    resp = await async_client.get("/api/analytics/summary?range=7&tz=UTC")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_clicks"] == 10
    assert data["previous_clicks"] == 5
    # (10 - 5) / 5 * 100 = 100.0%
    assert data["percent_change"] == 100.0


# =========================================================================
# 5. TIMESERIES ZERO-FILLING & EXACT N ENTRIES
# =========================================================================

@pytest.mark.anyio
async def test_analytics_timeseries_exact_n_entries(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    link = Link(user_id=user.id, short_code="tseries", original_url="https://example.com")
    db.add(link)
    db.commit()

    now = datetime.now(timezone.utc)
    # 3 clicks today, 2 clicks 2 days ago
    for _ in range(3):
        db.add(ClickEvent(link_id=link.id, clicked_at=now, referrer=None, device_type="mobile"))
    for _ in range(2):
        db.add(ClickEvent(link_id=link.id, clicked_at=now - timedelta(days=2), referrer=None, device_type="mobile"))
    db.commit()

    for r_days in (7, 30, 90):
        resp = await async_client.get(f"/api/analytics/timeseries?range={r_days}&tz=UTC")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == r_days
        total_in_items = sum(it["click_count"] for it in data["items"])
        assert total_in_items == 5


# =========================================================================
# 6. REFERRER MERGING (HTTP/HTTPS STRIP) & BREAKDOWN FORMATTING
# =========================================================================

@pytest.mark.anyio
async def test_analytics_breakdown_referrer_normalization(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    link = Link(user_id=user.id, short_code="reftest", original_url="https://example.com")
    db.add(link)
    db.commit()

    now = datetime.now(timezone.utc)

    # 4 clicks from http://google.com
    for _ in range(4):
        db.add(ClickEvent(link_id=link.id, clicked_at=now, referrer="http://google.com", device_type="desktop"))

    # 6 clicks from https://google.com/search (should merge to google.com)
    for _ in range(6):
        db.add(ClickEvent(link_id=link.id, clicked_at=now, referrer="https://google.com/search", device_type="mobile"))

    # 5 clicks direct (None)
    for _ in range(5):
        db.add(ClickEvent(link_id=link.id, clicked_at=now, referrer=None, device_type="desktop"))

    db.commit()

    resp = await async_client.get("/api/analytics/breakdown?range=30&tz=UTC")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_clicks"] == 15

    # Should have google.com with 10 clicks and Direct with 5 clicks
    ref_map = {r["name"]: r for r in data["referrers"]}
    assert "google.com" in ref_map
    assert ref_map["google.com"]["click_count"] == 10
    assert ref_map["google.com"]["percentage"] == round((10 / 15) * 100, 1)

    assert "Direct" in ref_map
    assert ref_map["Direct"]["click_count"] == 5
    assert ref_map["Direct"]["percentage"] == round((5 / 15) * 100, 1)

    # Devices: desktop (9), mobile (6)
    dev_map = {d["name"]: d for d in data["devices"]}
    assert dev_map["desktop"]["click_count"] == 9
    assert dev_map["mobile"]["click_count"] == 6


# =========================================================================
# 7. TOP LINKS ORDERING & TIE-BREAKING
# =========================================================================

@pytest.mark.anyio
async def test_analytics_top_links_tie_breaking(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    link1 = Link(user_id=user.id, short_code="link001", original_url="https://example.com/1")
    link2 = Link(user_id=user.id, short_code="link002", original_url="https://example.com/2")
    link3 = Link(user_id=user.id, short_code="link003", original_url="https://example.com/3")
    db.add_all([link1, link2, link3])
    db.commit()

    now = datetime.now(timezone.utc)
    # link3 has 10 clicks
    for _ in range(10):
        db.add(ClickEvent(link_id=link3.id, clicked_at=now, referrer=None, device_type="desktop"))
    # link1 and link2 both have 5 clicks (tie) -> ordered by id ASC (link1.id < link2.id)
    for _ in range(5):
        db.add(ClickEvent(link_id=link1.id, clicked_at=now, referrer=None, device_type="desktop"))
        db.add(ClickEvent(link_id=link2.id, clicked_at=now, referrer=None, device_type="desktop"))
    db.commit()

    resp = await async_client.get("/api/analytics/top-links?range=30&tz=UTC&limit=10")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    assert items[0]["id"] == link3.id
    assert items[0]["click_count"] == 10
    # Between link1 and link2 (both 5 clicks), link1 must come first because id is smaller
    assert items[1]["id"] == link1.id
    assert items[2]["id"] == link2.id


# =========================================================================
# 8. CROSS-USER LEAKAGE TESTS (ALL 4 ENDPOINTS)
# =========================================================================

@pytest.mark.anyio
async def test_cross_user_isolation(async_client: httpx.AsyncClient, auth_user, other_user, db):
    user_a, token_a = auth_user
    user_b, token_b = other_user

    link_a = Link(user_id=user_a.id, short_code="link_a", original_url="https://example.com/a")
    link_b = Link(user_id=user_b.id, short_code="link_b", original_url="https://example.com/b")
    db.add_all([link_a, link_b])
    db.commit()

    now = datetime.now(timezone.utc)
    # User B gets 50 clicks
    for _ in range(50):
        db.add(ClickEvent(link_id=link_b.id, clicked_at=now, referrer="https://b.com", device_type="desktop"))
    # User A gets 2 clicks
    for _ in range(2):
        db.add(ClickEvent(link_id=link_a.id, clicked_at=now, referrer="https://a.com", device_type="mobile"))
    db.commit()

    # User A queries
    async_client.cookies.set("session_token", token_a)

    # 1. Summary
    resp_sum = await async_client.get("/api/analytics/summary?range=30&tz=UTC")
    assert resp_sum.json()["current_clicks"] == 2

    # 2. Timeseries
    resp_ts = await async_client.get("/api/analytics/timeseries?range=7&tz=UTC")
    assert sum(i["click_count"] for i in resp_ts.json()["items"]) == 2

    # 3. Top Links
    resp_top = await async_client.get("/api/analytics/top-links?range=30&tz=UTC")
    items = resp_top.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == link_a.id

    # 4. Breakdown
    resp_bk = await async_client.get("/api/analytics/breakdown?range=30&tz=UTC")
    assert resp_bk.json()["total_clicks"] == 2


# =========================================================================
# 9. LINK_ID FILTER, IDOR, AND SOFT-DELETE GATING
# =========================================================================

@pytest.mark.anyio
async def test_link_filter_ownership_and_soft_delete(async_client: httpx.AsyncClient, auth_user, other_user, db):
    user_a, token_a = auth_user
    user_b, token_b = other_user

    link_a1 = Link(user_id=user_a.id, short_code="a_active", original_url="https://example.com/1")
    link_a_del = Link(user_id=user_a.id, short_code="a_del", original_url="https://example.com/2", deleted_at=datetime.now(timezone.utc))
    link_b = Link(user_id=user_b.id, short_code="b_active", original_url="https://example.com/3")
    db.add_all([link_a1, link_a_del, link_b])
    db.commit()

    now = datetime.now(timezone.utc)
    db.add(ClickEvent(link_id=link_a1.id, clicked_at=now, referrer=None, device_type="desktop"))
    db.commit()

    async_client.cookies.set("session_token", token_a)

    # 1. Filter by owned active link -> 200 OK
    resp_ok = await async_client.get(f"/api/analytics/summary?link_id={link_a1.id}")
    assert resp_ok.status_code == 200
    assert resp_ok.json()["current_clicks"] == 1
    assert resp_ok.json()["link_id"] == link_a1.id

    # 2. Filter by soft-deleted link -> 404
    resp_del = await async_client.get(f"/api/analytics/summary?link_id={link_a_del.id}")
    assert resp_del.status_code == 404

    # 3. Filter by other user's link (IDOR attempt) -> 404
    resp_idor = await async_client.get(f"/api/analytics/summary?link_id={link_b.id}")
    assert resp_idor.status_code == 404

    # 4. Filter by non-existent link -> 404
    resp_nonexistent = await async_client.get("/api/analytics/summary?link_id=999999")
    assert resp_nonexistent.status_code == 404


# =========================================================================
# 10. ADVERSARIAL VALIDATION & SQL INJECTION RESISTANCE
# =========================================================================

@pytest.mark.anyio
async def test_analytics_invalid_inputs_and_adversarial(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    # Invalid range (must be 7, 30, or 90)
    for bad_range in [0, 15, 60, -7, 100]:
        resp = await async_client.get(f"/api/analytics/summary?range={bad_range}")
        assert resp.status_code == 422

    # Invalid timezone (must return 422, never 500)
    for bad_tz in ["Not/ATimezone", "UTC; DROP TABLE click_events;--", ""]:
        resp = await async_client.get(f"/api/analytics/summary?tz={bad_tz}")
        assert resp.status_code == 422

    # Invalid limit on top-links (ge=1, le=50)
    for bad_limit in [0, -1, 51, 1000]:
        resp = await async_client.get(f"/api/analytics/top-links?limit={bad_limit}")
        assert resp.status_code == 422

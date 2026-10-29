import time
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import httpx

from app.core.config import settings
from app.users.models import User
from app.auth.service import create_user_session
from app.links.models import Link
from app.analytics.models import ClickEvent
from app.analytics.service import parse_device_type, sanitize_referrer


@pytest.fixture
def auth_user(db):
    user = User(email="owner@example.com", name="Link Owner")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token


@pytest.fixture
def other_user(db):
    user = User(email="other@example.com", name="Other User")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token


# =========================================================================
# 1. URL & EXPIRES_AT VALIDATION TESTS
# =========================================================================

@pytest.mark.anyio
async def test_create_link_valid_auto_code(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com/some/path?param=1"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["short_code"]) == 7
    assert data["short_url"] == f"{settings.SHORT_LINK_BASE_URL}/{data['short_code']}"
    assert data["original_url"] == "https://example.com/some/path?param=1"
    assert data["is_active"] is True
    assert data["click_count"] == 0
    assert data["expires_at"] is None


@pytest.mark.anyio
async def test_create_link_custom_alias(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com", "custom_code": "my-custom-slug_1"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 201
    assert resp.json()["short_code"] == "my-custom-slug_1"
    assert resp.json()["short_url"] == f"{settings.SHORT_LINK_BASE_URL}/my-custom-slug_1"


@pytest.mark.anyio
async def test_create_link_custom_alias_collision(async_client: httpx.AsyncClient, auth_user, other_user):
    user, token = auth_user
    other, other_token = other_user

    async_client.cookies.set("session_token", token)
    resp1 = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com/1", "custom_code": "taken-code"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp1.status_code == 201

    # Other user attempts same custom alias -> 409
    async_client.cookies.set("session_token", other_token)
    resp2 = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com/2", "custom_code": "taken-code"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp2.status_code == 409
    assert "already in use" in resp2.json()["detail"].lower()


@pytest.mark.anyio
@pytest.mark.parametrize("reserved", [
    "api", "API", "Docs", "DOCS", "redoc", "openapi.json", "health",
    "login", "Signup", "dashboard", "assets", "static", "favicon.ico", "robots.txt", "admin"
])
async def test_create_link_reserved_code_rejected(async_client: httpx.AsyncClient, auth_user, reserved):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com", "custom_code": reserved},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 422
    assert "reserved" in resp.text.lower()


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com",
    "http://user:password@example.com/path",  # credentials
    "http://user@example.com/path",           # user credential
    "https://example.com\x00/nullbyte",       # control char
    "https://example.com\x1f/control",        # control char
    f"{settings.SHORT_LINK_BASE_URL}/loop",   # redirect loop
    "not-a-url",
    "",
    "   ",
    "https://" + "a" * 2048 + ".com",         # length > 2048
])
async def test_create_link_invalid_urls_rejected(async_client: httpx.AsyncClient, auth_user, invalid_url):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.post(
        "/api/links",
        json={"original_url": invalid_url},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_link_expires_at_validation(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    # Past date -> 422
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    resp_past = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com", "expires_at": past},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_past.status_code == 422
    assert "future" in resp_past.text.lower()

    # Valid future date
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp_future = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com", "expires_at": future},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_future.status_code == 201
    assert resp_future.json()["expires_at"] is not None


# =========================================================================
# 2. CSRF & AUTH ENFORCEMENT
# =========================================================================

@pytest.mark.anyio
async def test_csrf_origin_rejected_on_state_changes(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    # 1. Foreign origin on POST
    resp1 = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com"},
        headers={"Origin": "https://evil-attacker.com"},
    )
    assert resp1.status_code == 403

    # 2. Foreign origin on PATCH
    resp2 = await async_client.patch(
        "/api/links/1",
        json={"is_active": False},
        headers={"Origin": "https://evil-attacker.com"},
    )
    assert resp2.status_code == 403

    # 3. Foreign origin on DELETE
    resp3 = await async_client.delete(
        "/api/links/1",
        headers={"Origin": "https://evil-attacker.com"},
    )
    assert resp3.status_code == 403


@pytest.mark.anyio
async def test_unauthenticated_links_endpoints_return_401(async_client: httpx.AsyncClient):
    # No session cookie
    valid_origin = {"Origin": settings.FRONTEND_ORIGIN}
    assert (await async_client.get("/api/links")).status_code == 401
    assert (await async_client.post("/api/links", json={"original_url": "https://example.com"}, headers=valid_origin)).status_code == 401
    assert (await async_client.get("/api/links/1")).status_code == 401
    assert (await async_client.patch("/api/links/1", json={"is_active": False}, headers=valid_origin)).status_code == 401
    assert (await async_client.delete("/api/links/1", headers=valid_origin)).status_code == 401


# =========================================================================
# 3. OWNERSHIP & IDOR PROTECTION
# =========================================================================

@pytest.mark.anyio
async def test_idor_protection(async_client: httpx.AsyncClient, auth_user, other_user):
    user, token = auth_user
    other, other_token = other_user

    # Owner creates a link
    async_client.cookies.set("session_token", token)
    create_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://owner-site.com", "custom_code": "owner-secret"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = create_resp.json()["id"]

    # Other user attempts to access owner's link -> MUST return 404 (prevent ID enumeration)
    async_client.cookies.set("session_token", other_token)

    resp_get = await async_client.get(f"/api/links/{link_id}")
    assert resp_get.status_code == 404

    resp_patch = await async_client.patch(
        f"/api/links/{link_id}",
        json={"is_active": False},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_patch.status_code == 404

    resp_delete = await async_client.delete(
        f"/api/links/{link_id}",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_delete.status_code == 404

    # Other user's link list must NOT contain owner's link
    list_resp = await async_client.get("/api/links")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0
    assert len(list_resp.json()["items"]) == 0


# =========================================================================
# 4. SOFT DELETE & IMMUTABLE DESTINATION URL
# =========================================================================

@pytest.mark.anyio
async def test_soft_delete_and_code_reservation(async_client: httpx.AsyncClient, auth_user, other_user, db):
    user, token = auth_user
    other, other_token = other_user

    async_client.cookies.set("session_token", token)
    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://example.com/target", "custom_code": "reserved-forever"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]

    # Delete link
    del_resp = await async_client.delete(f"/api/links/{link_id}", headers={"Origin": settings.FRONTEND_ORIGIN})
    assert del_resp.status_code == 200
    assert del_resp.json() == {"status": "deleted"}

    # Owner GET and PATCH return 404 for soft-deleted link
    assert (await async_client.get(f"/api/links/{link_id}")).status_code == 404
    assert (await async_client.patch(
        f"/api/links/{link_id}",
        json={"is_active": True},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )).status_code == 404

    # Excluded from link list
    list_resp = await async_client.get("/api/links")
    assert list_resp.json()["total"] == 0

    # Redirect on soft-deleted link returns 404 HTML
    redir_resp = await async_client.get("/reserved-forever", follow_redirects=False)
    assert redir_resp.status_code == 404
    assert "404 - Link Not Found" in redir_resp.text

    # Another user trying to create the same short code receives 409 Conflict
    async_client.cookies.set("session_token", other_token)
    recreate_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://attacker.com", "custom_code": "reserved-forever"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert recreate_resp.status_code == 409
    assert "already in use" in recreate_resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_patch_destination_url_forbidden(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://original.com"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]

    # Submitting original_url or other extra fields to PATCH is rejected (extra="forbid")
    patch_resp = await async_client.patch(
        f"/api/links/{link_id}",
        json={"original_url": "https://new-destination.com"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert patch_resp.status_code == 422


# =========================================================================
# 5. REDIRECTS, HEAD REQUESTS & CLICK ACCURACY
# =========================================================================

@pytest.mark.anyio
async def test_redirect_active_link(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://target-domain.com/hello", "custom_code": "redirect-test"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert c_resp.status_code == 201

    resp = await async_client.get(
        "/redirect-test",
        headers={
            "Referer": "https://twitter.com/some/tweet?id=123",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://target-domain.com/hello"
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_redirect_inactive_returns_404(async_client: httpx.AsyncClient, auth_user):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://target-domain.com"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]
    code = c_resp.json()["short_code"]

    # Deactivate link
    await async_client.patch(
        f"/api/links/{link_id}",
        json={"is_active": False},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )

    resp = await async_client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 404
    assert "404 - Link Not Found" in resp.text


@pytest.mark.anyio
async def test_redirect_expired_returns_410(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://target-domain.com"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]
    code = c_resp.json()["short_code"]

    # Manually expire the link in DB (since API rejects setting past expires_at)
    link = db.query(Link).filter_by(id=link_id).one()
    link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    resp = await async_client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 410
    assert "410 - Link Expired" in resp.text


@pytest.mark.anyio
async def test_head_request_redirects_without_recording_click(async_client: httpx.AsyncClient, auth_user, db):
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://head-target.com", "custom_code": "head-test"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]

    # HEAD request
    head_resp = await async_client.head("/head-test", follow_redirects=False)
    assert head_resp.status_code == 302
    assert head_resp.headers["location"] == "https://head-target.com"

    # Wait up to 1 second to confirm no background task was fired
    time.sleep(1)
    clicks = db.query(ClickEvent).filter_by(link_id=link_id).all()
    assert len(clicks) == 0


@pytest.mark.anyio
async def test_click_accuracy_n_redirects(async_client: httpx.AsyncClient, auth_user, db):
    """After N GET redirects, exactly N click_events rows exist with sanitized referrer and derived device_type."""
    user, token = auth_user
    async_client.cookies.set("session_token", token)

    c_resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://accuracy-target.com", "custom_code": "accuracy-test"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    link_id = c_resp.json()["id"]

    N = 5
    for i in range(N):
        resp = await async_client.get(
            "/accuracy-test",
            headers={
                "Referer": f"https://google.com/search?q=test_{i}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    # Poll up to 5 seconds for background tasks to complete
    start = time.time()
    click_count = 0
    while time.time() - start < 5.0:
        db.expire_all()
        click_count = db.query(ClickEvent).filter_by(link_id=link_id).count()
        if click_count == N:
            break
        time.sleep(0.1)

    assert click_count == N, f"Expected {N} click events, found {click_count}"

    # Verify click details
    events = db.query(ClickEvent).filter_by(link_id=link_id).all()
    for ev in events:
        assert ev.referrer == "https://google.com"  # scheme + host only!
        assert ev.device_type == "desktop"
        assert ev.country is None


# =========================================================================
# 6. DEVICE TYPE AND REFERRER UNIT TESTS
# =========================================================================

def test_device_type_classifier():
    assert parse_device_type("Googlebot/2.1 (+http://www.google.com/bot.html)") == "bot"
    assert parse_device_type("Mozilla/5.0 (compatible; bingbot/2.0)") == "bot"
    assert parse_device_type("Python-urllib/3.9") == "bot"
    assert parse_device_type("Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X)") == "tablet"
    assert parse_device_type("Mozilla/5.0 (iPhone; CPU iPhone OS 16_5)") == "mobile"
    assert parse_device_type("Mozilla/5.0 (Linux; Android 12; Pixel 6)") == "mobile"
    assert parse_device_type("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "desktop"
    assert parse_device_type("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)") == "desktop"
    assert parse_device_type("Mozilla/5.0 (X11; Linux x86_64)") == "desktop"
    assert parse_device_type(None) == "unknown"
    assert parse_device_type("") == "unknown"
    assert parse_device_type("UnknownAgent/1.0") == "unknown"


def test_sanitize_referrer():
    assert sanitize_referrer("https://news.ycombinator.com/item?id=12345#comments") == "https://news.ycombinator.com"
    assert sanitize_referrer("http://localhost:5173/dashboard") == "http://localhost:5173"
    assert sanitize_referrer(None) is None
    assert sanitize_referrer("") is None
    assert sanitize_referrer("invalid-uri-no-scheme") is None


# =========================================================================
# 7. PHASE 4 FIXES VERIFICATION TESTS (ITEMS 3 & 6)
# =========================================================================

@pytest.mark.anyio
async def test_post_links_sql_statement_count(async_client: httpx.AsyncClient, auth_user, test_engine):
    """Count SQL statements executed during a single POST /api/links request."""
    from sqlalchemy import event

    user, token = auth_user
    async_client.cookies.set("session_token", token)

    executed_statements = []

    def count_sql(conn, cursor, statement, parameters, context, executemany):
        executed_statements.append(statement.strip())

    event.listen(test_engine, "before_cursor_execute", count_sql)
    try:
        resp = await async_client.post(
            "/api/links",
            json={"original_url": "https://example.com/test-sql-count"},
            headers={"Origin": settings.FRONTEND_ORIGIN},
        )
        assert resp.status_code == 201
    finally:
        event.remove(test_engine, "before_cursor_execute", count_sql)

    # Filter out connection pool ping if any
    real_statements = [s for s in executed_statements if not s.startswith("SELECT 1")]
    print(f"\nSQL STATEMENTS COUNT: {len(real_statements)}")
    for i, st in enumerate(real_statements, 1):
        print(f"  {i}. {st.splitlines()[0]}")
    assert len(real_statements) <= 7, f"Expected <= 7 SQL statements, got {len(real_statements)}: {real_statements}"


@pytest.mark.anyio
async def test_post_links_no_dns_or_network_calls(async_client: httpx.AsyncClient, auth_user, monkeypatch):
    """Verify URL validation never makes DNS (getaddrinfo/gethostbyname) or socket network calls."""
    import socket

    def forbidden_dns(*args, **kwargs):
        raise AssertionError("FORBIDDEN: DNS resolution was attempted during URL validation!")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    monkeypatch.setattr(socket, "gethostbyname", forbidden_dns)
    monkeypatch.setattr(socket, "gethostbyname_ex", forbidden_dns)

    user, token = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.post(
        "/api/links",
        json={"original_url": "https://valid-external-destination.com/no-dns-test"},
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 201
    assert resp.json()["original_url"] == "https://valid-external-destination.com/no-dns-test"


@pytest.mark.anyio
async def test_html_error_pages_no_reflected_xss(async_client: httpx.AsyncClient):
    """HTML 404 and 410 error pages must never echo user input or short code unescaped (XSS safety)."""
    xss_payloads = [
        "<script>alert(1)",
        "<img src=x onerror=alert('xss')>",
        "\"><svg onload=alert(1)>",
        "';alert(1)",
        "<script>console.log(1)",
    ]

    for payload in xss_payloads:
        resp = await async_client.get(f"/{payload}", follow_redirects=False)
        assert resp.status_code == 404
        assert "text/html" in resp.headers.get("content-type", "")
        # Payload must NEVER appear in the response body
        assert payload not in resp.text
        assert "<script>" not in resp.text
        assert "onerror" not in resp.text
        assert "<svg" not in resp.text
        assert "404 - Link Not Found" in resp.text


import uuid
from datetime import datetime, timezone, timedelta
import pytest
import httpx

from app.core.config import settings
from app.users.models import User
from app.auth.models import AuthIdentity, Session
from app.auth.service import create_user_session


@pytest.fixture
def auth_user(db):
    user = User(email="settings_user@example.com", name="Settings User", avatar_url="https://example.com/avatar.png")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token, session


@pytest.fixture
def second_user(db):
    user = User(email="second_user@example.com", name="Second User")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    return user, raw_token, session


# =========================================================================
# 1. AUTHENTICATION & CSRF GATING
# =========================================================================

@pytest.mark.anyio
async def test_settings_endpoints_require_auth(async_client: httpx.AsyncClient):
    endpoints = [
        ("GET", "/api/me"),
        ("GET", "/api/me/identities"),
        ("GET", "/api/me/sessions"),
        ("POST", "/api/auth/logout-all"),
        ("DELETE", f"/api/me/sessions/{uuid.uuid4()}"),
    ]
    for method, ep in endpoints:
        resp = await async_client.request(method, ep, headers={"Origin": settings.FRONTEND_ORIGIN})
        assert resp.status_code == 401, f"{ep} failed to require auth"


@pytest.mark.anyio
async def test_settings_state_changing_enforces_csrf_origin(async_client: httpx.AsyncClient, auth_user):
    user, token, _ = auth_user
    async_client.cookies.set("session_token", token)

    # Missing Origin header -> 403
    resp_no_orig = await async_client.post("/api/auth/logout-all")
    assert resp_no_orig.status_code == 403

    # Foreign Origin header -> 403
    resp_bad_orig = await async_client.post(
        "/api/auth/logout-all",
        headers={"Origin": "https://evil.attacker.com"},
    )
    assert resp_bad_orig.status_code == 403

    # DELETE /api/me/sessions with bad Origin -> 403
    resp_del_bad = await async_client.delete(
        f"/api/me/sessions/{uuid.uuid4()}",
        headers={"Origin": "https://evil.attacker.com"},
    )
    assert resp_del_bad.status_code == 403


# =========================================================================
# 2. IDENTITIES ENDPOINT (GET /api/me/identities)
# =========================================================================

@pytest.mark.anyio
async def test_get_my_identities(async_client: httpx.AsyncClient, auth_user, db):
    user, token, _ = auth_user
    async_client.cookies.set("session_token", token)

    # Add Google and GitHub identities
    ident_google = AuthIdentity(
        user_id=user.id,
        provider="google",
        provider_user_id="google_sub_12345_secret",
        email_verified=True,
    )
    ident_github = AuthIdentity(
        user_id=user.id,
        provider="github",
        provider_user_id="github_id_67890_secret",
        email_verified=False,
    )
    db.add_all([ident_google, ident_github])
    db.commit()

    resp = await async_client.get("/api/me/identities")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 2
    for item in data:
        # Verified requirement: provider, email_verified, created_at only
        assert "provider" in item
        assert "email_verified" in item
        assert "created_at" in item
        # MUST NEVER return provider_user_id or email
        assert "provider_user_id" not in item
        assert "email" not in item
        assert "google_sub_12345_secret" not in str(item)
        assert "github_id_67890_secret" not in str(item)

    providers = [it["provider"] for it in data]
    assert "google" in providers
    assert "github" in providers


# =========================================================================
# 3. SESSIONS ENDPOINT & CURRENT SESSION MARKER (GET /api/me/sessions)
# =========================================================================

@pytest.mark.anyio
async def test_get_my_sessions_and_current_marker(async_client: httpx.AsyncClient, auth_user, db):
    user, token1, session1 = auth_user
    async_client.cookies.set("session_token", token1)

    # Create second active session for same user
    token2, session2 = create_user_session(db, user.id)

    # Create third expired session
    now = datetime.now(timezone.utc)
    expired_sess = Session(
        user_id=user.id,
        token_hash="expired_hash",
        created_at=now - timedelta(days=40),
        expires_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=10),
    )
    # Create fourth revoked session
    revoked_sess = Session(
        user_id=user.id,
        token_hash="revoked_hash",
        created_at=now - timedelta(days=5),
        expires_at=now + timedelta(days=25),
        last_seen_at=now - timedelta(days=1),
        revoked_at=now - timedelta(hours=2),
    )
    # Create fifth idle-timeout expired session
    idle_expired_sess = Session(
        user_id=user.id,
        token_hash="idle_expired_hash",
        created_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=20),
        last_seen_at=now - timedelta(hours=settings.SESSION_IDLE_TIMEOUT_HOURS + 1),
    )
    db.add_all([expired_sess, revoked_sess, idle_expired_sess])
    db.commit()

    resp = await async_client.get("/api/me/sessions")
    assert resp.status_code == 200
    data = resp.json()

    # List MUST exclude expired, revoked, and idle-expired sessions
    assert len(data) == 2

    # Verify no token_hash is ever returned
    for s in data:
        assert "token_hash" not in s
        assert "id" in s
        assert "created_at" in s
        assert "expires_at" in s
        assert "last_seen_at" in s
        assert "is_current" in s

    # Session 1 must be marked is_current: True; Session 2 must be is_current: False
    s1_item = next(it for it in data if it["id"] == str(session1.id))
    s2_item = next(it for it in data if it["id"] == str(session2.id))
    assert s1_item["is_current"] is True
    assert s2_item["is_current"] is False


# =========================================================================
# 4. REVOKE SINGLE SESSION (DELETE /api/me/sessions/{id})
# =========================================================================

@pytest.mark.anyio
async def test_revoke_other_session(async_client: httpx.AsyncClient, auth_user, second_user, db):
    user, token1, session1 = auth_user
    async_client.cookies.set("session_token", token1)

    # Create session 2 for user A
    token2, session2 = create_user_session(db, user.id)

    # User B's session
    _, _, session_b = second_user

    # 1. Malformed UUID -> 422
    resp_malformed = await async_client.delete(
        "/api/me/sessions/not-a-valid-uuid",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_malformed.status_code == 422

    # 2. Non-existent UUID -> 404
    resp_404 = await async_client.delete(
        f"/api/me/sessions/{uuid.uuid4()}",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_404.status_code == 404

    # 3. IDOR attempt: try to delete User B's session -> 404
    resp_idor = await async_client.delete(
        f"/api/me/sessions/{session_b.id}",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_idor.status_code == 404
    # User B's session remains unrevoked
    db.refresh(session_b)
    assert session_b.revoked_at is None

    # 4. Revoke user A's second session -> 200 OK
    resp_ok = await async_client.delete(
        f"/api/me/sessions/{session2.id}",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp_ok.status_code == 200
    db.refresh(session2)
    assert session2.revoked_at is not None

    # Requesting with token 2 now fails with 401
    async_client.cookies.set("session_token", token2)
    resp_token2 = await async_client.get("/api/me")
    assert resp_token2.status_code == 401

    # Requesting with token 1 (current session) still succeeds
    async_client.cookies.set("session_token", token1)
    resp_token1 = await async_client.get("/api/me")
    assert resp_token1.status_code == 200


@pytest.mark.anyio
async def test_revoke_current_session_clears_cookie(async_client: httpx.AsyncClient, auth_user, db):
    user, token, session = auth_user
    async_client.cookies.set("session_token", token)

    resp = await async_client.delete(
        f"/api/me/sessions/{session.id}",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 200

    # Verify session cookie was deleted/cleared in response
    deleted_cookie = resp.cookies.get("session_token")
    assert deleted_cookie is None or deleted_cookie == ""

    # Subsequent request returns 401
    resp_me = await async_client.get("/api/me")
    assert resp_me.status_code == 401


# =========================================================================
# 5. LOGOUT ALL (POST /api/auth/logout-all)
# =========================================================================

@pytest.mark.anyio
async def test_logout_all_revokes_all_user_sessions_and_leaves_others(async_client: httpx.AsyncClient, auth_user, second_user, db):
    user_a, token_a1, sess_a1 = auth_user
    token_a2, sess_a2 = create_user_session(db, user_a.id)

    user_b, token_b, sess_b = second_user

    async_client.cookies.set("session_token", token_a1)

    # User A calls logout-all
    resp = await async_client.post(
        "/api/auth/logout-all",
        headers={"Origin": settings.FRONTEND_ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "logged_out_everywhere"

    # Both of User A's sessions are now marked revoked_at
    db.refresh(sess_a1)
    db.refresh(sess_a2)
    assert sess_a1.revoked_at is not None
    assert sess_a2.revoked_at is not None

    # User B's session was NOT touched
    db.refresh(sess_b)
    assert sess_b.revoked_at is None

    # Token A1 returns 401
    async_client.cookies.set("session_token", token_a1)
    resp_a1 = await async_client.get("/api/me")
    assert resp_a1.status_code == 401

    # Token A2 returns 401
    async_client.cookies.set("session_token", token_a2)
    resp_a2 = await async_client.get("/api/me")
    assert resp_a2.status_code == 401

    # Token B continues to work
    async_client.cookies.set("session_token", token_b)
    resp_b = await async_client.get("/api/me")
    assert resp_b.status_code == 200
    assert resp_b.json()["id"] == str(user_b.id)


# =========================================================================
# 6. SHARED HELPER UNIT TESTS (is_session_active)
# =========================================================================

def test_is_session_active_helper():
    from app.auth.service import is_session_active
    now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Active session
    sess = Session(
        user_id=uuid.uuid4(),
        token_hash="hash",
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        last_seen_at=now - timedelta(hours=1),
        revoked_at=None,
    )
    assert is_session_active(sess, now=now) is True

    # 2. Revoked session
    sess_revoked = Session(
        user_id=uuid.uuid4(),
        token_hash="hash",
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        last_seen_at=now - timedelta(hours=1),
        revoked_at=now - timedelta(minutes=10),
    )
    assert is_session_active(sess_revoked, now=now) is False

    # 3. Expired session
    sess_expired = Session(
        user_id=uuid.uuid4(),
        token_hash="hash",
        created_at=now - timedelta(days=35),
        expires_at=now - timedelta(days=5),
        last_seen_at=now - timedelta(days=5),
        revoked_at=None,
    )
    assert is_session_active(sess_expired, now=now) is False

    # 4. Idle expired session (> SESSION_IDLE_TIMEOUT_HOURS)
    sess_idle = Session(
        user_id=uuid.uuid4(),
        token_hash="hash",
        created_at=now - timedelta(days=5),
        expires_at=now + timedelta(days=25),
        last_seen_at=now - timedelta(hours=settings.SESSION_IDLE_TIMEOUT_HOURS + 1),
        revoked_at=None,
    )
    assert is_session_active(sess_idle, now=now) is False

    # 5. None session
    assert is_session_active(None, now=now) is False

    # 6. Session with no last_seen_at (freshly created before first access)
    sess_no_seen = Session(
        user_id=uuid.uuid4(),
        token_hash="hash",
        created_at=now,
        expires_at=now + timedelta(days=30),
        last_seen_at=None,
        revoked_at=None,
    )
    assert is_session_active(sess_no_seen, now=now) is True


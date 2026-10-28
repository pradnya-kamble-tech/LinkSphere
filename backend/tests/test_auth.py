import base64
import json
import uuid
from datetime import datetime, timezone, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import respx
import httpx

from app.core.config import settings
from app.core.security import (
    generate_random_string,
    create_signed_oauth_state,
    hash_session_token,
    generate_session_token,
)
from app.users.models import User
from app.auth.models import AuthIdentity, Session
from app.auth.service import create_user_session, find_or_create_user_and_identity


def make_mock_jwt(claims: dict) -> str:
    """Build a mock 3-part JWT with given claims."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.mock_signature"


@pytest.mark.anyio
async def test_oauth_login_redirect_google(async_client: httpx.AsyncClient):
    """Initiating Google login must redirect with state, PKCE, and set oauth_state cookie."""
    resp = await async_client.get("/api/auth/google/login?next=/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert "nonce=" in location
    assert "state=" in location
    assert "oauth_state" in resp.cookies


@pytest.mark.anyio
async def test_oauth_login_redirect_github(async_client: httpx.AsyncClient):
    """Initiating GitHub login must redirect with state and set oauth_state cookie."""
    resp = await async_client.get("/api/auth/github/login?next=/", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize")
    assert "state=" in location
    assert "oauth_state" in resp.cookies


@pytest.mark.anyio
async def test_oauth_login_unsupported_provider(async_client: httpx.AsyncClient):
    """Unsupported provider returns HTTP 400."""
    resp = await async_client.get("/api/auth/facebook/login")
    assert resp.status_code == 400
    assert "Unsupported OAuth provider" in resp.json()["detail"]


@pytest.mark.anyio
@respx.mock
async def test_google_callback_new_user(async_client: httpx.AsyncClient, db):
    """Google OAuth callback creates new user, identity, session, and sets cookie."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    verifier = "mock_verifier_string"
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": verifier,
    })

    id_token = make_mock_jwt({
        "sub": "google-10001",
        "email": "google_new@example.com",
        "email_verified": True,
        "name": "Google New User",
        "picture": "https://example.com/pic.jpg",
        "nonce": nonce,
    })

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": id_token, "access_token": "mock_at"})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(
        f"/api/auth/callback/google?code=good_code&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/dashboard"
    assert "session_token" in resp.cookies
    assert "oauth_state" not in resp.cookies or resp.cookies.get("oauth_state") == ""

    # Verify user in database
    user = db.query(User).filter_by(email="google_new@example.com").first()
    assert user is not None
    assert user.name == "Google New User"

    ident = db.query(AuthIdentity).filter_by(provider="google", provider_user_id="google-10001").first()
    assert ident is not None
    assert ident.user_id == user.id
    assert ident.email_verified is True


@pytest.mark.anyio
@respx.mock
async def test_google_callback_returning_user(async_client: httpx.AsyncClient, db):
    """Returning user logs in, reuses existing user, and creates new session."""
    user = User(email="returning@example.com", name="Existing User")
    db.add(user)
    db.commit()

    ident = AuthIdentity(user_id=user.id, provider="google", provider_user_id="google-sub-20002", email_verified=True)
    db.add(ident)
    db.commit()

    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "ver",
    })

    id_token = make_mock_jwt({
        "sub": "google-sub-20002",
        "email": "returning@example.com",
        "email_verified": True,
        "name": "Existing User",
        "nonce": nonce,
    })

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=good_code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert "session_token" in resp.cookies

    # Ensure no duplicate user was created
    assert db.query(User).filter_by(email="returning@example.com").count() == 1


@pytest.mark.anyio
@respx.mock
async def test_account_linking_verified_email(async_client: httpx.AsyncClient, db):
    """Second provider with same verified email links to existing user without creating new user."""
    # Existing user registered via Google
    user = User(email="shared@example.com", name="Shared User")
    db.add(user)
    db.commit()

    google_ident = AuthIdentity(user_id=user.id, provider="google", provider_user_id="sub-111", email_verified=True)
    db.add(google_ident)
    db.commit()

    # Login via GitHub with same verified email
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "gh_token_123"})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": 554433, "login": "ghuser", "name": "GitHub Shared"})
    )
    respx.get("https://api.github.com/user/emails").mock(
        return_value=httpx.Response(200, json=[
            {"email": "shared@example.com", "primary": True, "verified": True}
        ])
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=gh_code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/dashboard"

    # Verify single user with both identities
    assert db.query(User).filter_by(email="shared@example.com").count() == 1
    identities = db.query(AuthIdentity).filter_by(user_id=user.id).all()
    providers = {i.provider for i in identities}
    assert providers == {"google", "github"}
    gh_ident = db.query(AuthIdentity).filter_by(provider="github", provider_user_id="554433").first()
    assert gh_ident is not None
    assert gh_ident.user_id == user.id


@pytest.mark.anyio
@respx.mock
async def test_refusal_to_link_unverified_email(async_client: httpx.AsyncClient, db):
    """Unverified email from provider must be rejected and redirect to /login?error=email_not_verified."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    id_token = make_mock_jwt({
        "sub": "google-unverified",
        "email": "unverified@example.com",
        "email_verified": False,
        "nonce": nonce,
    })

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=email_not_verified"
    assert "session_token" not in resp.cookies
    assert db.query(User).filter_by(email="unverified@example.com").first() is None


@pytest.mark.anyio
@respx.mock
async def test_github_hidden_email_resolution(async_client: httpx.AsyncClient, db):
    """GitHub account with hidden emails extracts primary verified email from /user/emails."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "gh_tok"})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": 776655, "login": "octocat", "name": "The Octocat"})
    )
    # Emails list with unverified/non-primary and one primary+verified
    respx.get("https://api.github.com/user/emails").mock(
        return_value=httpx.Response(200, json=[
            {"email": "secondary@example.com", "primary": False, "verified": True},
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "primary_verified@example.com", "primary": True, "verified": True},
        ])
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/dashboard"

    user = db.query(User).filter_by(email="primary_verified@example.com").first()
    assert user is not None
    assert user.name == "The Octocat"


@pytest.mark.anyio
@respx.mock
async def test_github_no_verified_email_fails(async_client: httpx.AsyncClient, db):
    """GitHub account without a primary verified email redirects to /login?error=no_verified_email."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "gh_tok"})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": 8888, "login": "noverified"})
    )
    respx.get("https://api.github.com/user/emails").mock(
        return_value=httpx.Response(200, json=[
            {"email": "not_verified@example.com", "primary": True, "verified": False}
        ])
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=no_verified_email"
    assert "session_token" not in resp.cookies


@pytest.mark.anyio
async def test_callback_state_mismatch(async_client: httpx.AsyncClient):
    """State mismatch redirects to /login?error=invalid_state."""
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": "correct_state",
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })
    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get("/api/auth/callback/google?code=code&state=wrong_state", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_state"


@pytest.mark.anyio
async def test_callback_missing_state_cookie(async_client: httpx.AsyncClient):
    """Missing state cookie redirects to /login?error=invalid_state."""
    resp = await async_client.get("/api/auth/callback/google?code=code&state=somestate", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_state"


@pytest.mark.anyio
@respx.mock
async def test_google_nonce_mismatch(async_client: httpx.AsyncClient):
    """Nonce mismatch between id_token and state redirects to /login?error=invalid_nonce."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": "expected_nonce_123",
        "code_verifier": "v",
    })

    id_token = make_mock_jwt({
        "sub": "google-badnonce",
        "email": "nonce@example.com",
        "email_verified": True,
        "nonce": "tampered_nonce_999",
    })

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_nonce"


@pytest.mark.anyio
async def test_get_me_authenticated(async_client: httpx.AsyncClient, db):
    """GET /api/me with valid session cookie returns user data."""
    user = User(email="me@example.com", name="Me User")
    db.add(user)
    db.commit()

    raw_token, _ = create_user_session(db, user.id)
    async_client.cookies.set("session_token", raw_token)

    resp = await async_client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(user.id)
    assert data["email"] == "me@example.com"
    assert data["name"] == "Me User"


@pytest.mark.anyio
async def test_get_me_unauthenticated(async_client: httpx.AsyncClient):
    """GET /api/me without cookie returns 401."""
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.anyio
async def test_get_me_expired_session(async_client: httpx.AsyncClient, db):
    """Expired session returns 401."""
    user = User(email="expired@example.com")
    db.add(user)
    db.commit()

    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    now = datetime.now(timezone.utc)
    # Expired 1 hour ago
    session = Session(user_id=user.id, token_hash=token_hash, created_at=now - timedelta(days=8), expires_at=now - timedelta(hours=1))
    db.add(session)
    db.commit()

    async_client.cookies.set("session_token", raw_token)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_me_revoked_session(async_client: httpx.AsyncClient, db):
    """Revoked session returns 401."""
    user = User(email="revoked@example.com")
    db.add(user)
    db.commit()

    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    now = datetime.now(timezone.utc)
    session = Session(user_id=user.id, token_hash=token_hash, created_at=now, expires_at=now + timedelta(days=7), revoked_at=now)
    db.add(session)
    db.commit()

    async_client.cookies.set("session_token", raw_token)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_logout_flow(async_client: httpx.AsyncClient, db):
    """Logout revokes session, clears cookie, and invalidates subsequent /api/me."""
    user = User(email="logout@example.com")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
    async_client.cookies.set("session_token", raw_token)

    # Valid me
    resp = await async_client.get("/api/me")
    assert resp.status_code == 200

    # Logout with valid Origin
    logout_resp = await async_client.post("/api/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "logged_out"}

    # Verify session is revoked in database
    db.refresh(session)
    assert session.revoked_at is not None

    # Subsequent me returns 401
    me_resp = await async_client.get("/api/me")
    assert me_resp.status_code == 401


@pytest.mark.anyio
async def test_logout_csrf_origin_rejected(async_client: httpx.AsyncClient, db):
    """POST /api/auth/logout rejects mismatched Origin."""
    user = User(email="csrf@example.com")
    db.add(user)
    db.commit()
    raw_token, _ = create_user_session(db, user.id)
    async_client.cookies.set("session_token", raw_token)

    # Foreign origin
    resp = await async_client.post("/api/auth/logout", headers={"Origin": "http://evil-attacker.com"})
    assert resp.status_code == 403

    # Missing origin
    resp_no_origin = await async_client.post("/api/auth/logout")
    assert resp_no_origin.status_code == 403


@pytest.mark.anyio
async def test_open_redirect_prevention(async_client: httpx.AsyncClient):
    """Unapproved next URL in login is forced to /dashboard in signed state."""
    # Attempt next=https://malicious.com
    resp = await async_client.get("/api/auth/google/login?next=https://malicious.com", follow_redirects=False)
    assert resp.status_code == 302
    # Verify the cookie contains /dashboard instead of external link
    signed_cookie = resp.cookies["oauth_state"]
    from app.core.security import verify_signed_oauth_state
    payload = verify_signed_oauth_state(signed_cookie)
    assert payload is not None
    assert payload["next"] == "/dashboard"


@pytest.mark.anyio
async def test_cookie_with_token_hash_attack(async_client: httpx.AsyncClient, db):
    """Passing stored token_hash value in cookie instead of raw token fails."""
    user = User(email="hashattack@example.com")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)

    # Attacker passes the hash from the DB in their cookie
    async_client.cookies.set("session_token", session.token_hash)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401


def test_concurrent_first_login_callbacks(TestSessionLocal, db):
    """Two concurrent threads completing callback for same new user: savepoint ensures single user creation."""
    results = []
    barrier = threading.Barrier(2)

    def worker(worker_id):
        session = TestSessionLocal()
        try:
            barrier.wait(timeout=5)
            user = find_or_create_user_and_identity(
                db=session,
                provider="google",
                provider_user_id=f"sub-concurrent-{worker_id}",
                email="concurrent_race@example.com",
                email_verified=True,
                name="Race User",
            )
            results.append(("SUCCESS", user.id))
        except Exception as e:
            results.append(("ERROR", str(e)))
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker, 1)
        f2 = executor.submit(worker, 2)
        f1.result()
        f2.result()

    assert all(r[0] == "SUCCESS" for r in results), f"Expected both workers to succeed, got {results}"
    user_ids = [r[1] for r in results]
    assert user_ids[0] == user_ids[1], f"Expected both workers to resolve the same user ID, got {user_ids}"

    # Verify single user in DB with 2 identities
    user = db.query(User).filter_by(email="concurrent_race@example.com").one()
    assert len(user.identities) == 2


@pytest.mark.anyio
async def test_last_seen_at_throttling(async_client: httpx.AsyncClient, db):
    """sessions.last_seen_at is updated only if stored value is older than 5 minutes."""
    user = User(email="throttle@example.com")
    db.add(user)
    db.commit()
    raw_token, session = create_user_session(db, user.id)
    initial_last_seen = session.last_seen_at

    async_client.cookies.set("session_token", raw_token)

    # 1. Request immediately (stored value is fresh < 5m)
    await async_client.get("/api/me")
    db.refresh(session)
    assert session.last_seen_at == initial_last_seen

    # 2. Simulate stored value older than 5 minutes (e.g. 6 minutes ago)
    session.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    db.commit()

    await async_client.get("/api/me")
    db.refresh(session)
    assert session.last_seen_at > initial_last_seen

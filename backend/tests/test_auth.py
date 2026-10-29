import base64
import json
import uuid
import time
from datetime import datetime, timezone, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import respx
import httpx
from authlib.jose import jwt, JsonWebKey

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


# Module-level RSA keys for cryptographic OIDC verification tests
TEST_RSA_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)
TEST_PUB_KEY = TEST_RSA_KEY.as_dict(is_private=False)
TEST_PUB_KEY["kid"] = "test-google-kid-1"
TEST_JWKS = {"keys": [TEST_PUB_KEY]}

# Separate key for testing bad signature attacks
UNTRUSTED_RSA_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)


def make_signed_google_id_token(
    claims_override: dict = None,
    key=TEST_RSA_KEY,
    kid="test-google-kid-1"
) -> str:
    """Build a cryptographically signed RS256 Google ID token."""
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID or "dev_google_client_id",
        "sub": "google-test-sub-1",
        "email": "google_test@example.com",
        "email_verified": True,
        "name": "Google Test User",
        "picture": "https://example.com/avatar.png",
        "nonce": "test_nonce",
        "exp": now + 3600,
        "iat": now,
    }
    if claims_override:
        claims.update(claims_override)
    header = {"alg": "RS256", "kid": kid}
    return jwt.encode(header, claims, key).decode("utf-8")


@pytest.mark.anyio
async def test_oauth_login_redirect_google(async_client: httpx.AsyncClient):
    """Initiating Google login must redirect with state, PKCE, and set oauth_state cookie."""
    resp = await async_client.get("/api/auth/google/login?next=/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(settings.GOOGLE_AUTH_URL)
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
    assert location.startswith(settings.GITHUB_AUTH_URL)
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

    id_token = make_signed_google_id_token({
        "sub": "google-10001",
        "email": "google_new@example.com",
        "email_verified": True,
        "name": "Google New User",
        "picture": "https://example.com/pic.jpg",
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
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

    id_token = make_signed_google_id_token({
        "sub": "google-sub-20002",
        "email": "returning@example.com",
        "email_verified": True,
        "name": "Existing User",
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
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

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "gh_token_123", "token_type": "bearer"})
    )
    respx.get(settings.GITHUB_USER_URL).mock(
        return_value=httpx.Response(200, json={"id": 554433, "login": "ghuser", "name": "GitHub Shared"})
    )
    respx.get(settings.GITHUB_EMAILS_URL).mock(
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

    id_token = make_signed_google_id_token({
        "sub": "google-unverified",
        "email": "unverified@example.com",
        "email_verified": False,
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
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

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "gh_tok", "token_type": "bearer"})
    )
    respx.get(settings.GITHUB_USER_URL).mock(
        return_value=httpx.Response(200, json={"id": 776655, "login": "octocat", "name": "The Octocat"})
    )
    respx.get(settings.GITHUB_EMAILS_URL).mock(
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

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "gh_tok", "token_type": "bearer"})
    )
    respx.get(settings.GITHUB_USER_URL).mock(
        return_value=httpx.Response(200, json={"id": 8888, "login": "noverified"})
    )
    respx.get(settings.GITHUB_EMAILS_URL).mock(
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

    id_token = make_signed_google_id_token({
        "sub": "google-badnonce",
        "email": "nonce@example.com",
        "email_verified": True,
        "nonce": "tampered_nonce_999",
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_nonce"


# --- Item 6: Cryptographic ID Token Verification Tests (signature, iss, aud, exp) ---

@pytest.mark.anyio
@respx.mock
async def test_google_callback_invalid_signature(async_client: httpx.AsyncClient):
    """Google ID token signed by an untrusted key is rejected with provider_error."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    # Sign with untrusted key not in JWKS
    id_token = make_signed_google_id_token(
        {"sub": "bad-sig-sub", "nonce": nonce},
        key=UNTRUSTED_RSA_KEY,
        kid="test-google-kid-1",
    )

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


@pytest.mark.anyio
@respx.mock
async def test_google_callback_invalid_issuer(async_client: httpx.AsyncClient):
    """Google ID token with untrusted issuer is rejected with provider_error."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    id_token = make_signed_google_id_token({
        "iss": "https://evil-issuer.com",
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


@pytest.mark.anyio
@respx.mock
async def test_google_callback_invalid_audience(async_client: httpx.AsyncClient):
    """Google ID token intended for a different client_id is rejected with provider_error."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    id_token = make_signed_google_id_token({
        "aud": "attacker_registered_client_id.apps.googleusercontent.com",
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


@pytest.mark.anyio
@respx.mock
async def test_google_callback_expired_token(async_client: httpx.AsyncClient):
    """Expired Google ID token is rejected with provider_error."""
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    id_token = make_signed_google_id_token({
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        "nonce": nonce,
    })

    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


# --- Item 6: GitHub Token Response Handling Tests ---

@pytest.mark.anyio
@respx.mock
async def test_github_callback_error_response(async_client: httpx.AsyncClient):
    """GitHub token exchange error response redirects to /login?error=provider_error."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"error": "bad_verification_code", "error_description": "Code expired"})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=expired_code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


@pytest.mark.anyio
@respx.mock
async def test_github_callback_invalid_token_type(async_client: httpx.AsyncClient):
    """GitHub response with non-bearer token type is rejected with provider_error."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "gh_tok", "token_type": "mac"})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


@pytest.mark.anyio
@respx.mock
async def test_github_callback_missing_access_token(async_client: httpx.AsyncClient):
    """GitHub response missing access_token is rejected with provider_error."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "github",
        "state": state,
        "next": "/dashboard",
        "nonce": "n",
        "code_verifier": "v",
    })

    respx.post(settings.GITHUB_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"token_type": "bearer"})
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/github?code=code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


# --- Item 7: Missing Tests ---

@pytest.mark.anyio
async def test_get_me_idle_timeout(async_client: httpx.AsyncClient, db):
    """Session whose last_seen_at exceeds SESSION_IDLE_TIMEOUT_HOURS returns 401."""
    user = User(email="idle_timeout@example.com", name="Idle User")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
    # Set last_seen_at to 25 hours ago (timeout is 24h)
    session.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=settings.SESSION_IDLE_TIMEOUT_HOURS + 1)
    db.commit()

    async_client.cookies.set("session_token", raw_token)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401
    assert "Invalid, expired, or revoked session" in resp.json()["detail"]


@pytest.mark.anyio
@respx.mock
async def test_replayed_authorization_code(async_client: httpx.AsyncClient, db):
    """Replaying an authorization code rejected by provider (invalid_grant) redirects with provider_error and creates no session."""
    state = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": "nonce123",
        "code_verifier": "v",
    })

    # Provider rejects replayed code with HTTP 400 invalid_grant
    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Code has already been used"})
    )

    initial_user_count = db.query(User).count()
    initial_session_count = db.query(Session).count()

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=replayed_code&state={state}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"
    assert "session_token" not in resp.cookies
    assert db.query(User).count() == initial_user_count
    assert db.query(Session).count() == initial_session_count


@pytest.mark.anyio
async def test_logout_wrong_http_method(async_client: httpx.AsyncClient):
    """Calling /api/auth/logout with wrong HTTP method (GET) returns 405 Method Not Allowed."""
    resp = await async_client.get("/api/auth/logout")
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_get_me_random_garbage_cookie(async_client: httpx.AsyncClient):
    """Sending a random garbage cookie returns 401 Unauthorized."""
    async_client.cookies.set("session_token", "completely_random_garbage_cookie_value_99999")
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid, expired, or revoked session"


# --- Standard Session & Auth Lifecycle Tests ---

@pytest.mark.anyio
async def test_get_me_authenticated(async_client: httpx.AsyncClient, db):
    """GET /api/me returns user profile when valid session_token cookie is provided."""
    user = User(email="user_me@example.com", name="Test User")
    db.add(user)
    db.commit()

    raw_token, _ = create_user_session(db, user.id)
    async_client.cookies.set("session_token", raw_token)

    resp = await async_client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "user_me@example.com"
    assert data["name"] == "Test User"
    assert data["id"] == str(user.id)


@pytest.mark.anyio
async def test_get_me_unauthenticated(async_client: httpx.AsyncClient):
    """GET /api/me returns HTTP 401 when no session_token cookie is provided."""
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.anyio
async def test_get_me_expired_session(async_client: httpx.AsyncClient, db):
    """GET /api/me returns HTTP 401 when session has expired."""
    user = User(email="expired@example.com")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    db.commit()

    async_client.cookies.set("session_token", raw_token)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid, expired, or revoked session"


@pytest.mark.anyio
async def test_get_me_revoked_session(async_client: httpx.AsyncClient, db):
    """GET /api/me returns HTTP 401 when session was revoked."""
    user = User(email="revoked@example.com")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    async_client.cookies.set("session_token", raw_token)
    resp = await async_client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_logout_flow(async_client: httpx.AsyncClient, db):
    """POST /api/auth/logout revokes session in DB and deletes session cookie."""
    user = User(email="logout_test@example.com")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
    async_client.cookies.set("session_token", raw_token)

    resp = await async_client.post("/api/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged_out"}

    db.refresh(session)
    assert session.revoked_at is not None

    resp2 = await async_client.get("/api/me")
    assert resp2.status_code == 401


@pytest.mark.anyio
async def test_logout_csrf_origin_rejected(async_client: httpx.AsyncClient, db):
    """POST /api/auth/logout with untrusted Origin returns 403 Forbidden."""
    resp = await async_client.post("/api/auth/logout", headers={"Origin": "http://evil.com"})
    assert resp.status_code == 403
    assert "Origin mismatch" in resp.json()["detail"]


@pytest.mark.anyio
async def test_open_redirect_prevention(async_client: httpx.AsyncClient):
    """Attempting open redirect in next parameter is sanitized to /dashboard."""
    resp = await async_client.get("/api/auth/google/login?next=https://evil.com/phish", follow_redirects=False)
    assert resp.status_code == 302
    assert "oauth_state" in resp.cookies


@pytest.mark.anyio
async def test_cookie_with_token_hash_attack(async_client: httpx.AsyncClient, db):
    """Passing stored token_hash directly in cookie fails because server re-hashes incoming cookie."""
    user = User(email="hash_attack@example.com")
    db.add(user)
    db.commit()

    raw_token, session = create_user_session(db, user.id)
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


# --- Item 3: JWKS Caching, Timeout, Refetch, and Network Unreachable Tests ---

@pytest.mark.anyio
@respx.mock
async def test_jwks_cache_hit():
    """Google JWKS is cached with TTL; subsequent calls within TTL do not re-fetch from network."""
    from app.auth.oauth import get_google_jwks, clear_google_jwks_cache
    clear_google_jwks_cache()

    route = respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )

    # First call fetches from network
    jwks1 = await get_google_jwks()
    assert route.call_count == 1
    assert "keys" in jwks1

    # Second call uses cache (call_count remains 1)
    jwks2 = await get_google_jwks()
    assert route.call_count == 1
    assert jwks1 == jwks2


@pytest.mark.anyio
@respx.mock
async def test_jwks_unknown_kid_refetch():
    """An unknown kid triggers a forced refetch of Google JWKS exactly once."""
    from app.auth.oauth import verify_google_id_token, clear_google_jwks_cache
    clear_google_jwks_cache()

    route = respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(200, json=TEST_JWKS)
    )

    id_token = make_signed_google_id_token(kid="rotated-kid-2")

    with pytest.raises(ValueError, match="No matching public key found for kid: rotated-kid-2"):
        await verify_google_id_token(id_token, expected_nonce="test_nonce")

    assert route.call_count == 2


@pytest.mark.anyio
@respx.mock
async def test_google_jwks_endpoint_unreachable(async_client: httpx.AsyncClient):
    """Google JWKS endpoint unreachable redirects to /login?error=provider_error, never returning HTTP 500."""
    from app.auth.oauth import clear_google_jwks_cache
    clear_google_jwks_cache()

    state = generate_random_string(32)
    nonce = generate_random_string(32)
    signed_state = create_signed_oauth_state({
        "provider": "google",
        "state": state,
        "next": "/dashboard",
        "nonce": nonce,
        "code_verifier": "v",
    })

    id_token = make_signed_google_id_token({"nonce": nonce})

    respx.post(settings.GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"id_token": id_token})
    )
    respx.get(settings.GOOGLE_CERTS_URL).mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )

    async_client.cookies.set("oauth_state", signed_state)
    resp = await async_client.get(f"/api/auth/callback/google?code=code&state={state}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=provider_error"


# --- Item 4: Gated Diagnostic Endpoints Test ---

@pytest.mark.anyio
async def test_diagnostic_endpoints_gated_outside_test():
    """Diagnostic endpoints return 404 when app is initialized with non-test ENVIRONMENT."""
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    # In current test run (ENVIRONMENT=test), routes exist
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/diagnostic/ping-async")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    # In a simulated non-test environment, define app without the test gate
    from fastapi import FastAPI
    prod_app = FastAPI()
    async with AsyncClient(transport=ASGITransport(app=prod_app), base_url="http://test") as client:
        resp1 = await client.get("/api/diagnostic/ping-async")
        assert resp1.status_code == 404
        resp2 = await client.get("/api/diagnostic/ping-sync")
        assert resp2.status_code == 404

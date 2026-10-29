import base64
import hashlib
import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
from authlib.jose import jwt, JsonWebKey
from authlib.jose.errors import JoseError, BadSignatureError, ExpiredTokenError, InvalidClaimError

from app.core.config import settings

_google_jwks_cache: Optional[Dict[str, Any]] = None
_google_jwks_cache_time: float = 0.0
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """Return reusable shared HTTP client with keep-alive connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        )
    return _http_client


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def get_google_auth_url(redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
    """Construct Google OAuth2 authorization URL with PKCE and nonce."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{settings.GOOGLE_AUTH_URL}?{urlencode(params)}"


def get_github_auth_url(redirect_uri: str, state: str) -> str:
    """Construct GitHub OAuth authorization URL."""
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    return f"{settings.GITHUB_AUTH_URL}?{urlencode(params)}"


async def get_google_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch and cache Google's public JSON Web Key Set."""
    global _google_jwks_cache, _google_jwks_cache_time
    now = time.time()
    if not force_refresh and _google_jwks_cache and (now - _google_jwks_cache_time < 3600):
        return _google_jwks_cache

    client = get_http_client()
    resp = await client.get(settings.GOOGLE_CERTS_URL)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch Google JWKS: status {resp.status_code}")
    _google_jwks_cache = resp.json()
    _google_jwks_cache_time = now
    return _google_jwks_cache


def clear_google_jwks_cache() -> None:
    """Clear in-memory JWKS cache (for tests)."""
    global _google_jwks_cache, _google_jwks_cache_time
    _google_jwks_cache = None
    _google_jwks_cache_time = 0.0


async def exchange_google_code(
    code: str, redirect_uri: str, code_verifier: str
) -> Dict[str, Any]:
    """Exchange authorization code for tokens with Google."""
    client = get_http_client()
    resp = await client.post(
        settings.GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Google token exchange failed: status {resp.status_code}")
    return resp.json()


def extract_jwt_header(token: str) -> Dict[str, Any]:
    """Decode unverified JWT header."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    header_b64 = parts[0]
    rem = len(header_b64) % 4
    if rem:
        header_b64 += "=" * (4 - rem)
    return json.loads(base64.urlsafe_b64decode(header_b64).decode("utf-8"))


async def verify_google_id_token(id_token: str, expected_nonce: str) -> Dict[str, Any]:
    """
    Cryptographically verify Google OIDC ID token:
    1. Signature verified against Google's public JWKS.
    2. Issuer verified ('https://accounts.google.com' or 'accounts.google.com').
    3. Audience verified matching GOOGLE_CLIENT_ID.
    4. Expiration verified (not expired).
    5. Nonce verified matching state cookie.
    6. email_verified claim verified as True.
    """
    # 1. Parse unverified header to extract kid
    try:
        header = extract_jwt_header(id_token)
    except Exception as e:
        raise ValueError(f"Invalid id_token header: {e}")

    kid = header.get("kid")
    if not kid:
        raise ValueError("Missing kid in id_token header")

    # 2. Match kid against Google JWKS
    try:
        jwks = await get_google_jwks()
    except Exception as e:
        raise ValueError(f"Google JWKS fetch failed: {e}")

    keys = jwks.get("keys", [])
    matching_key = next((k for k in keys if k.get("kid") == kid), None)

    if not matching_key:
        # Key rotation fallback: force refresh JWKS once
        try:
            jwks = await get_google_jwks(force_refresh=True)
            matching_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        except Exception as e:
            raise ValueError(f"Google JWKS refresh failed: {e}")

    if not matching_key:
        raise ValueError(f"No matching public key found for kid: {kid}")

    # 3. Decode & cryptographically verify signature, iss, aud, exp
    claims_options = {
        "iss": {
            "essential": True,
            "values": ["https://accounts.google.com", "accounts.google.com"],
        },
        "aud": {
            "essential": True,
            "values": [settings.GOOGLE_CLIENT_ID],
        },
        "exp": {
            "essential": True,
        },
    }

    try:
        claims = jwt.decode(id_token, matching_key, claims_options=claims_options)
        claims.validate()
    except ExpiredTokenError:
        raise ValueError("Google id_token has expired")
    except BadSignatureError:
        raise ValueError("Google id_token signature verification failed")
    except InvalidClaimError as e:
        raise ValueError(f"Google id_token claim validation failed: {e}")
    except JoseError as e:
        raise ValueError(f"Google id_token verification error: {e}")

    # 4. Verify nonce
    if claims.get("nonce") != expected_nonce:
        raise ValueError("Google id_token nonce mismatch")

    # 5. Verify email_verified
    if not claims.get("email_verified"):
        raise ValueError("Google account email is not verified")

    if not claims.get("email"):
        raise ValueError("Google id_token missing email claim")

    return dict(claims)


async def exchange_github_code(code: str, redirect_uri: str) -> str:
    """
    Exchange authorization code for GitHub access token:
    - Verifies HTTP 200.
    - Rejects response if error or error_description present.
    - Verifies token_type is bearer.
    - Verifies access_token is present and non-empty.
    """
    client = get_http_client()
    resp = await client.post(
        settings.GITHUB_TOKEN_URL,
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub token exchange HTTP error: {resp.status_code}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(
            f"GitHub token exchange error: {data.get('error_description') or data.get('error')}"
        )
    token_type = data.get("token_type", "")
    if token_type.lower() != "bearer":
        raise RuntimeError(f"Unexpected GitHub token_type: {token_type}")
    access_token = data.get("access_token")
    if not access_token or not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("Missing or empty GitHub access token")
    return access_token


async def fetch_github_profile(access_token: str) -> Dict[str, Any]:
    """
    Fetch GitHub user profile and primary verified email:
    - Enforces numeric id presence.
    - Resolves primary AND verified email from /user/emails.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LinkSphere-Auth",
    }
    client = get_http_client()
    user_resp = await client.get(settings.GITHUB_USER_URL, headers=headers)
    if user_resp.status_code != 200:
        raise RuntimeError(f"GitHub user profile fetch failed: {user_resp.status_code}")
    user_data = user_resp.json()
    if not user_data.get("id"):
        raise RuntimeError("GitHub user profile missing id")

    emails_resp = await client.get(settings.GITHUB_EMAILS_URL, headers=headers)
    if emails_resp.status_code != 200:
        raise RuntimeError(f"GitHub emails fetch failed: {emails_resp.status_code}")
    emails_data = emails_resp.json()

    primary_verified_email = None
    if isinstance(emails_data, list):
        for entry in emails_data:
            if entry.get("primary") is True and entry.get("verified") is True:
                primary_verified_email = entry.get("email")
                break

    return {
        "id": str(user_data["id"]),
        "name": user_data.get("name") or user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "email": primary_verified_email,
        "email_verified": bool(primary_verified_email),
    }

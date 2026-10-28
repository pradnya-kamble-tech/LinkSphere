import base64
import hashlib
import json
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
from app.core.config import settings
from app.core.security import generate_random_string


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
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def get_github_auth_url(redirect_uri: str, state: str) -> str:
    """Construct GitHub OAuth authorization URL."""
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    return f"https://github.com/login/oauth/authorize?{urlencode(params)}"


async def exchange_google_code(
    code: str, redirect_uri: str, code_verifier: str
) -> Dict[str, Any]:
    """Exchange authorization code for tokens with Google."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
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
            raise RuntimeError(f"Google token exchange failed: {resp.status_code}")
        return resp.json()


def parse_unverified_id_token_payload(id_token: str) -> Dict[str, Any]:
    """Decode JWT payload without cryptographic verification for extraction (payload verified by TLS exchange)."""
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid id_token format")
    payload_b64 = parts[1]
    # Add padding
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    decoded_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(decoded_bytes.decode("utf-8"))


async def exchange_github_code(code: str, redirect_uri: str) -> str:
    """Exchange code for GitHub access token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GitHub token exchange failed: {resp.status_code}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("GitHub access token not returned")
        return token


async def fetch_github_profile(access_token: str) -> Dict[str, Any]:
    """Fetch GitHub user profile and primary verified email."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LinkSphere-Auth",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Fetch user profile
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code != 200:
            raise RuntimeError(f"GitHub user profile fetch failed: {user_resp.status_code}")
        user_data = user_resp.json()

        # Fetch emails
        emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
        if emails_resp.status_code != 200:
            raise RuntimeError(f"GitHub emails fetch failed: {emails_resp.status_code}")
        emails_data = emails_resp.json()

    # Find primary and verified email
    primary_verified_email = None
    if isinstance(emails_data, list):
        for entry in emails_data:
            if entry.get("primary") is True and entry.get("verified") is True:
                primary_verified_email = entry.get("email")
                break

    return {
        "id": str(user_data["id"]),  # Numeric ID as string
        "name": user_data.get("name") or user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "email": primary_verified_email,
        "email_verified": bool(primary_verified_email),
    }

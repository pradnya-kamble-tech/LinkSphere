import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    generate_random_string,
    validate_next_path,
    create_signed_oauth_state,
    verify_signed_oauth_state,
)
from app.auth.dependencies import verify_csrf_origin
from app.auth.oauth import (
    generate_pkce_pair,
    get_google_auth_url,
    get_github_auth_url,
    exchange_google_code,
    verify_google_id_token,
    exchange_github_code,
    fetch_github_profile,
)
from app.auth.service import (
    find_or_create_user_and_identity,
    create_user_session,
    revoke_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/{provider}/login")
async def oauth_login(
    provider: str,
    request: Request,
    next: Optional[str] = "/dashboard",
):
    """Initiate OAuth authorization with Google or GitHub."""
    if provider not in ("google", "github"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}",
        )

    validated_next = validate_next_path(next)
    state = generate_random_string(32)
    nonce = generate_random_string(32)
    verifier, challenge = generate_pkce_pair()

    state_payload = {
        "provider": provider,
        "state": state,
        "next": validated_next,
        "nonce": nonce,
        "code_verifier": verifier,
    }
    signed_state = create_signed_oauth_state(state_payload)

    redirect_uri = f"{settings.FRONTEND_ORIGIN}/api/auth/callback/{provider}"

    if provider == "google":
        auth_url = get_google_auth_url(redirect_uri, state, nonce, challenge)
    else:
        auth_url = get_github_auth_url(redirect_uri, state)

    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="oauth_state",
        value=signed_state,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=600,
        path="/",
    )
    return response


@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Handle OAuth provider callback with fixed-code redirection on error."""
    error_param = request.query_params.get("error")
    if error_param:
        code = "access_denied" if error_param == "access_denied" else "provider_error"
        return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error={code}", status_code=status.HTTP_302_FOUND)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    signed_state_cookie = request.cookies.get("oauth_state")

    if not code or not state or not signed_state_cookie:
        return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=invalid_state", status_code=status.HTTP_302_FOUND)

    payload = verify_signed_oauth_state(signed_state_cookie)
    if not payload or payload.get("state") != state or payload.get("provider") != provider:
        return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=invalid_state", status_code=status.HTTP_302_FOUND)

    redirect_uri = f"{settings.FRONTEND_ORIGIN}/api/auth/callback/{provider}"

    try:
        if provider == "google":
            token_data = await exchange_google_code(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=payload.get("code_verifier", ""),
            )
            id_token = token_data.get("id_token")
            if not id_token:
                return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=provider_error", status_code=status.HTTP_302_FOUND)

            try:
                claims = await verify_google_id_token(
                    id_token=id_token,
                    expected_nonce=payload.get("nonce", ""),
                )
            except ValueError as ve:
                err_msg = str(ve)
                if "nonce" in err_msg:
                    err_code = "invalid_nonce"
                elif "not verified" in err_msg:
                    err_code = "email_not_verified"
                elif "missing email" in err_msg:
                    err_code = "no_verified_email"
                else:
                    err_code = "provider_error"
                return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error={err_code}", status_code=status.HTTP_302_FOUND)

            email = claims["email"]
            provider_user_id = str(claims["sub"])
            name = claims.get("name")
            avatar_url = claims.get("picture")

        elif provider == "github":
            access_token = await exchange_github_code(code=code, redirect_uri=redirect_uri)
            profile = await fetch_github_profile(access_token)

            if not profile.get("email_verified") or not profile.get("email"):
                return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=no_verified_email", status_code=status.HTTP_302_FOUND)

            provider_user_id = str(profile["id"])
            email = profile["email"]
            name = profile.get("name")
            avatar_url = profile.get("avatar_url")
        else:
            return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=provider_error", status_code=status.HTTP_302_FOUND)

        # Concurrency-safe find-or-create inside single transaction with savepoint
        # Run synchronous DB operations in threadpool to prevent blocking the asyncio event loop
        user = await run_in_threadpool(
            find_or_create_user_and_identity,
            db=db,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            email_verified=True,
            name=name,
            avatar_url=avatar_url,
        )

        raw_token, _ = await run_in_threadpool(create_user_session, db, user.id)

        target_path = validate_next_path(payload.get("next"))
        response = RedirectResponse(
            f"{settings.FRONTEND_ORIGIN}{target_path}",
            status_code=status.HTTP_302_FOUND,
        )
        response.delete_cookie("oauth_state", path="/")
        response.set_cookie(
            key="session_token",
            value=raw_token,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=settings.SESSION_LIFETIME_DAYS * 86400,
            path="/",
        )
        return response

    except Exception:
        # Never log tokens or secrets
        logger.exception("OAuth callback processing encountered an error")
        return RedirectResponse(f"{settings.FRONTEND_ORIGIN}/login?error=provider_error", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf_origin),
):
    """Revoke session and clear session cookie. Enforces matching Origin."""
    raw_token = request.cookies.get("session_token")
    if raw_token:
        revoke_session(db, raw_token)

    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(key="session_token", path="/")
    return response


import secrets

from fastapi.testclient import TestClient

from app.core.security import (
    create_session,
    get_user_from_session,
    revoke_session,
)
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User


client = TestClient(app)


def test_revoked_session_cannot_authenticate():
    db = SessionLocal()
    user = None

    try:
        user = User(
            email=f"session-test-{secrets.token_hex(8)}@example.com"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        raw_token, _ = create_session(db, user.id)

        # A newly created session should authenticate.
        assert get_user_from_session(db, raw_token) is not None

        # Revocation should succeed.
        assert revoke_session(db, raw_token) is True

        # The revoked token must no longer authenticate.
        assert get_user_from_session(db, raw_token) is None

        # Revoking it a second time should not succeed.
        assert revoke_session(db, raw_token) is False

    finally:
        if user is not None:
            db.delete(user)
            db.commit()
        db.close()


def test_logout_clears_session_cookie():
    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Logged out successfully"
    }

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie


def test_current_user_requires_authentication():
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."

def test_registration_rejects_invalid_verification_token():
    response = client.post(
        "/auth/register/verify",
        json={"token": "definitely-not-a-valid-token"},
    )

    assert response.status_code == 400
    assert "invalid, expired, or already used" in response.json()["detail"]


def test_registration_request_returns_generic_response():
    response = client.post(
        "/auth/register",
        json={"email": f"new-user-{secrets.token_hex(8)}@example.com"},
    )

    assert response.status_code == 202
    assert "verification email will be sent" in response.json()["message"]

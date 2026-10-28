from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user
from app.users.models import User

router = APIRouter(tags=["users"])


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """Return authenticated user profile or 401."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }

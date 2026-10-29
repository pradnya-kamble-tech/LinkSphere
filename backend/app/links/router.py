from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.auth.dependencies import get_current_user, verify_csrf_origin
from app.users.models import User
from app.links.schemas import LinkCreate, LinkUpdate, LinkRead, LinkListResponse
from app.links import service

router = APIRouter(prefix="/links", tags=["links"])


def to_link_read(link, click_count: int = 0) -> LinkRead:
    return LinkRead(
        id=link.id,
        short_code=link.short_code,
        short_url=service.build_short_url(link.short_code),
        original_url=link.original_url,
        is_active=link.is_active,
        expires_at=link.expires_at,
        created_at=link.created_at,
        click_count=click_count,
    )


@router.post(
    "",
    response_model=LinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf_origin)],
)
def create_link(
    link_in: LinkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new short link with optional custom code and expiration."""
    link = service.create_link(db, current_user.id, link_in)
    return to_link_read(link, 0)


@router.get("", response_model=LinkListResponse)
def list_links(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List authenticated user's links paginated, ordered by created_at DESC with page-level click counts."""
    items, total, click_counts = service.get_user_links(
        db, current_user.id, limit=limit, offset=offset
    )
    link_reads = [to_link_read(l, click_counts.get(l.id, 0)) for l in items]
    return LinkListResponse(items=link_reads, total=total, limit=limit, offset=offset)


@router.get("/{link_id}", response_model=LinkRead)
def get_link(
    link_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get single link owned by current user."""
    link, click_count = service.get_link_by_id(db, link_id, current_user.id)
    return to_link_read(link, click_count)


@router.patch(
    "/{link_id}",
    response_model=LinkRead,
    dependencies=[Depends(verify_csrf_origin)],
)
def update_link(
    link_id: int,
    link_update: LinkUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update link mutable fields (is_active, expires_at). Destination URL is immutable."""
    link, click_count = service.update_link(db, link_id, current_user.id, link_update)
    return to_link_read(link, click_count)


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_csrf_origin)],
)
def delete_link(
    link_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete link. The short code remains reserved; click events are kept."""
    service.soft_delete_link(db, link_id, current_user.id)
    return {"status": "deleted"}

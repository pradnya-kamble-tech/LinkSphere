import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.links.models import Link
from app.analytics.models import ClickEvent
from app.links.schemas import LinkCreate, LinkUpdate, RESERVED_CODES

BASE62_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase


def generate_short_code(length: int = 7) -> str:
    """Generate a random base62 short code of specified length, avoiding reserved words."""
    while True:
        code = "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))
        if code.lower() not in RESERVED_CODES:
            return code


def build_short_url(short_code: str) -> str:
    """Build canonical short URL using configured SHORT_LINK_BASE_URL."""
    base = settings.SHORT_LINK_BASE_URL.rstrip("/")
    return f"{base}/{short_code}"


def create_link(db: Session, user_id: uuid.UUID, link_in: LinkCreate) -> Link:
    """
    Create a new link for the user.
    Handles custom aliases and auto-generated base62 codes.
    Rely strictly on the database unique constraint + savepoint retry for collision
    handling without redundant pre-check round-trips.
    """
    if link_in.custom_code:
        custom = link_in.custom_code
        link = Link(
            user_id=user_id,
            short_code=custom,
            original_url=link_in.original_url,
            expires_at=link_in.expires_at,
            is_active=True,
        )
        nested = db.begin_nested()
        try:
            db.add(link)
            nested.commit()
            db.commit()
            db.refresh(link)
            return link
        except IntegrityError:
            nested.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Short code '{custom}' is already in use",
            )

    # Auto-generated short code with collision retry up to 3 times in a savepoint
    for attempt in range(3):
        code = generate_short_code(7)
        nested = db.begin_nested()
        try:
            link = Link(
                user_id=user_id,
                short_code=code,
                original_url=link_in.original_url,
                expires_at=link_in.expires_at,
                is_active=True,
            )
            db.add(link)
            nested.commit()
            db.commit()
            db.refresh(link)
            return link
        except IntegrityError:
            nested.rollback()
            continue

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to allocate unique short code after 3 attempts",
    )


def get_user_links(
    db: Session, user_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> Tuple[List[Link], int, Dict[int, int]]:
    """
    Retrieve paginated links owned by user (excluding soft-deleted).
    Computes total count and grouped click counts ONLY for the links on this page.
    """
    # 1. Total count
    count_stmt = select(func.count(Link.id)).where(
        Link.user_id == user_id,
        Link.deleted_at.is_(None),
    )
    total = db.execute(count_stmt).scalar() or 0

    # 2. Paginated items
    items_stmt = (
        select(Link)
        .where(
            Link.user_id == user_id,
            Link.deleted_at.is_(None),
        )
        .order_by(Link.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.execute(items_stmt).scalars().all())

    # 3. Grouped click counts only for IDs on this page
    click_counts: Dict[int, int] = {}
    if items:
        page_ids = [l.id for l in items]
        clicks_stmt = (
            select(ClickEvent.link_id, func.count(ClickEvent.id))
            .where(ClickEvent.link_id.in_(page_ids))
            .group_by(ClickEvent.link_id)
        )
        click_counts = dict(db.execute(clicks_stmt).all())

    return items, total, click_counts


def get_link_by_id(db: Session, link_id: int, user_id: uuid.UUID) -> Tuple[Link, int]:
    """Retrieve single link owned by user with its click count, or raise 404."""
    stmt = select(Link).where(
        Link.id == link_id,
        Link.user_id == user_id,
        Link.deleted_at.is_(None),
    )
    link = db.execute(stmt).scalar_one_or_none()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found",
        )

    clicks_stmt = select(func.count(ClickEvent.id)).where(ClickEvent.link_id == link_id)
    click_count = db.execute(clicks_stmt).scalar() or 0
    return link, click_count


def update_link(
    db: Session, link_id: int, user_id: uuid.UUID, link_update: LinkUpdate
) -> Tuple[Link, int]:
    """Update link mutable fields (is_active, expires_at). Destination URL is not editable."""
    link, click_count = get_link_by_id(db, link_id, user_id)

    if link_update.is_active is not None:
        link.is_active = link_update.is_active
    if link_update.expires_at is not None:
        link.expires_at = link_update.expires_at

    db.commit()
    db.refresh(link)
    return link, click_count


def soft_delete_link(db: Session, link_id: int, user_id: uuid.UUID) -> None:
    """Soft delete link by setting deleted_at = now(UTC). Click events are preserved."""
    stmt = select(Link).where(
        Link.id == link_id,
        Link.user_id == user_id,
        Link.deleted_at.is_(None),
    )
    link = db.execute(stmt).scalar_one_or_none()
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found",
        )

    link.deleted_at = datetime.now(timezone.utc)
    db.commit()

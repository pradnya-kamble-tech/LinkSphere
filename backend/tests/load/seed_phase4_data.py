import os
import sys
import uuid
import time
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.users.models import User
from app.auth.models import Session
from app.links.models import Link
from app.analytics.models import ClickEvent
from app.auth.service import create_user_session

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
assert TEST_DB_URL.endswith("_test"), "ABORT: Not test DB"


def seed_phase4_heavy_data():
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # 1. Seed heavy user
    user = db.execute(select(User).where(User.email == "phase4_heavy@example.com")).scalar_one_or_none()
    if not user:
        user = User(email="phase4_heavy@example.com", name="Phase4 Heavy User")
        db.add(user)
        db.commit()
        db.refresh(user)

    # User session token
    raw_token, _ = create_user_session(db, user.id)

    # 2. Check existing link count for this user
    link_count = db.execute(select(func.count(Link.id)).where(Link.user_id == user.id)).scalar() or 0
    if link_count < 1000:
        needed = 1000 - link_count
        print(f"Seeding {needed} links for {user.email}...")
        now_utc = datetime.now(timezone.utc)
        link_mappings = []
        for i in range(link_count + 1, 1001):
            link_mappings.append({
                "user_id": user.id,
                "short_code": f"hvy_{i}_{int(time.time())}",
                "original_url": f"https://example.com/dest/{i}",
                "is_active": True,
                "created_at": now_utc,
            })
        db.bulk_insert_mappings(Link, link_mappings)
        db.commit()

    # Get all link IDs for this user
    link_ids = list(db.execute(select(Link.id).where(Link.user_id == user.id)).scalars().all())

    # 3. Check existing click count for this user's links
    click_count = db.execute(select(func.count(ClickEvent.id)).where(ClickEvent.link_id.in_(link_ids))).scalar() or 0
    if click_count < 100000:
        needed_clicks = 100000 - click_count
        print(f"Seeding {needed_clicks} click events in batches of 10,000...")
        now_utc = datetime.now(timezone.utc)
        chunk_size = 10000
        for chunk_start in range(0, needed_clicks, chunk_size):
            chunk_n = min(chunk_size, needed_clicks - chunk_start)
            click_mappings = []
            for j in range(chunk_n):
                l_id = link_ids[(chunk_start + j) % len(link_ids)]
                click_mappings.append({
                    "link_id": l_id,
                    "clicked_at": now_utc,
                    "referrer": "https://google.com",
                    "device_type": "desktop",
                    "country": None,
                })
            db.bulk_insert_mappings(ClickEvent, click_mappings)
            db.commit()
            print(f"  -> Inserted {chunk_start + chunk_n}/{needed_clicks} click events")

    # 4. Seed dedicated redirect link
    redir_link = db.execute(select(Link).where(Link.short_code == "redir50")).scalar_one_or_none()
    if not redir_link:
        redir_link = Link(
            user_id=user.id,
            short_code="redir50",
            original_url="https://example.com/redirect-dest",
            is_active=True,
        )
        db.add(redir_link)
        db.commit()
        db.refresh(redir_link)

    # Clear prior click events on redir50
    db.execute(text("DELETE FROM click_events WHERE link_id = :lid"), {"lid": redir_link.id})
    db.commit()

    redir_link_id = redir_link.id
    user_id = user.id
    db.close()
    return user_id, raw_token, redir_link_id


if __name__ == "__main__":
    u_id, token, redir_id = seed_phase4_heavy_data()
    print(f"Done! User: {u_id}, Token: {token[:10]}..., Redir Link ID: {redir_id}")

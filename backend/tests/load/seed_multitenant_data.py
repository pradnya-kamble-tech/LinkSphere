import os
import sys
import time
import random
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"

def seed_multitenant_dataset():
    print("=== POPULATING 1,000,000 ROW MULTI-TENANT CLICK DATASET ===")
    t0 = time.time()
    engine = create_engine(TEST_DB_URL)
    
    with engine.connect() as conn:
        print("Cleaning tables...")
        conn.execute(text("TRUNCATE TABLE click_events, links, sessions, auth_identities, users RESTART IDENTITY CASCADE;"))
        conn.commit()

        # 1. Heavy User (20 links, 100k clicks)
        heavy_uid = "fd12a248-e232-4ffc-b12f-892285f15f05"
        print(f"Creating heavy user {heavy_uid}...")
        conn.execute(
            text("INSERT INTO users (id, email, name, created_at, updated_at) VALUES (:uid, 'testuser@example.com', 'Heavy Test User', now(), now())"),
            {"uid": heavy_uid}
        )
        heavy_token = "test_phase6_session_token_1234567890"
        heavy_token_hash = hashlib.sha256(heavy_token.encode("utf-8")).hexdigest()
        conn.execute(
            text("INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at) VALUES ('11111111-1111-1111-1111-111111111111', :uid, :th, now(), now() + interval '30 days')"),
            {"uid": heavy_uid, "th": heavy_token_hash}
        )
        # 20 links for heavy user (IDs 1..20)
        conn.execute(text("""
            INSERT INTO links (user_id, short_code, original_url, is_active, created_at)
            SELECT 'fd12a248-e232-4ffc-b12f-892285f15f05', 'heavy_' || i, 'https://example.com/heavy/' || i, true, now()
            FROM generate_series(1, 20) i;
        """))
        conn.commit()

        # 2. Typical User (20 links, 2k clicks)
        typical_uid = "22222222-2222-2222-2222-222222222222"
        print(f"Creating typical user {typical_uid}...")
        conn.execute(
            text("INSERT INTO users (id, email, name, created_at, updated_at) VALUES (:uid, 'typical@example.com', 'Typical User', now(), now())"),
            {"uid": typical_uid}
        )
        typical_token = "typical_phase6_session_token_1234567890"
        typical_token_hash = hashlib.sha256(typical_token.encode("utf-8")).hexdigest()
        conn.execute(
            text("INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at) VALUES ('22222222-2222-2222-2222-222222222222', :uid, :th, now(), now() + interval '30 days')"),
            {"uid": typical_uid, "th": typical_token_hash}
        )
        # 20 links for typical user (IDs 21..40)
        conn.execute(text("""
            INSERT INTO links (user_id, short_code, original_url, is_active, created_at)
            SELECT '22222222-2222-2222-2222-222222222222', 'typ_' || i, 'https://example.com/typ/' || i, true, now()
            FROM generate_series(1, 20) i;
        """))
        conn.commit()

        # 3. 50 other users with 20 links each (1000 other links, IDs 41..1040)
        print("Creating 50 other users with 20 links each...")
        conn.execute(text("""
            INSERT INTO users (id, email, name, created_at, updated_at)
            SELECT gen_random_uuid(), 'other_' || i || '@example.com', 'Other User ' || i, now(), now()
            FROM generate_series(1, 50) i;
        """))
        conn.execute(text("""
            INSERT INTO links (user_id, short_code, original_url, is_active, created_at)
            SELECT u.id, 'oth_' || substr(replace(u.id::text, '-', ''), 1, 10) || '_' || i, 'https://example.com/other/' || i, true, now()
            FROM (SELECT id FROM users WHERE email NOT IN ('testuser@example.com', 'typical@example.com')) u
            CROSS JOIN generate_series(1, 20) i;
        """))
        conn.commit()

        # 4. Generate 100,000 clicks for heavy test user (links 1 to 20)
        print("Generating 100,000 clicks for heavy user...")
        conn.execute(text("""
            INSERT INTO click_events (link_id, clicked_at, referrer, device_type)
            SELECT
                (1 + (i % 20)) AS link_id,
                now() - (random() * interval '90 days') AS clicked_at,
                (ARRAY['https://google.com', 'https://twitter.com', 'https://github.com', 'https://reddit.com', NULL])[1 + floor(random() * 5)::int] AS referrer,
                (ARRAY['desktop', 'mobile', 'tablet', 'bot', 'unknown'])[1 + floor(random() * 5)::int] AS device_type
            FROM generate_series(1, 100000) i;
        """))
        conn.commit()

        # 5. Generate 2,000 clicks for typical user (links 21 to 40)
        print("Generating 2,000 clicks for typical user...")
        conn.execute(text("""
            INSERT INTO click_events (link_id, clicked_at, referrer, device_type)
            SELECT
                (21 + (i % 20)) AS link_id,
                now() - (random() * interval '90 days') AS clicked_at,
                (ARRAY['https://google.com', 'https://twitter.com', 'https://github.com', 'https://reddit.com', NULL])[1 + floor(random() * 5)::int] AS referrer,
                (ARRAY['desktop', 'mobile', 'tablet', 'bot', 'unknown'])[1 + floor(random() * 5)::int] AS device_type
            FROM generate_series(1, 2000) i;
        """))
        conn.commit()

        # 6. Generate 898,000 clicks for other 50 users (links 41 to 1040)
        print("Generating 898,000 clicks for other 50 users...")
        conn.execute(text("""
            INSERT INTO click_events (link_id, clicked_at, referrer, device_type)
            SELECT
                (41 + (i % 1000)) AS link_id,
                now() - (random() * interval '90 days') AS clicked_at,
                (ARRAY['https://google.com', 'https://twitter.com', 'https://github.com', 'https://reddit.com', NULL])[1 + floor(random() * 5)::int] AS referrer,
                (ARRAY['desktop', 'mobile', 'tablet', 'bot', 'unknown'])[1 + floor(random() * 5)::int] AS device_type
            FROM generate_series(1, 898000) i;
        """))
        conn.commit()

        # 7. Run ANALYZE
        print("Running ANALYZE...")
        conn.execute(text("ANALYZE click_events; ANALYZE links; ANALYZE users;"))
        conn.commit()

        total_clicks = conn.execute(text("SELECT count(*) FROM click_events;")).scalar()
        heavy_clicks = conn.execute(text("""
            SELECT count(c.id) FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = 'fd12a248-e232-4ffc-b12f-892285f15f05';
        """)).scalar()
        typ_clicks = conn.execute(text("""
            SELECT count(c.id) FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = '22222222-2222-2222-2222-222222222222';
        """)).scalar()
        print(f"Dataset ready in {time.time() - t0:.2f}s: Total = {total_clicks}, Heavy = {heavy_clicks}, Typical = {typ_clicks}")

if __name__ == "__main__":
    seed_multitenant_dataset()

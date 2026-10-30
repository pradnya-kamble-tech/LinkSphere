import sys, os
sys.path.insert(0, os.path.abspath("."))
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from app.analytics.service import calculate_range_boundaries, build_binary_case

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
USER_ID = "fd12a248-e232-4ffc-b12f-892285f15f05"
LINK_ID = 1

def run_plans():
    engine = create_engine(TEST_DB_URL)
    bounds = calculate_range_boundaries(30, "UTC")
    day_ranges = bounds["day_ranges"]
    binary_case_expr = build_binary_case(day_ranges)

    cur_start = bounds["current_start_utc"]
    cur_end = bounds["current_end_utc"]
    prev_start = bounds["prev_start_utc"]
    prev_end = bounds["prev_end_utc"]

    params = {
        "user_id": USER_ID,
        "link_id": LINK_ID,
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "limit": 10,
    }

    queries = {
        "1a. Summary (Single Link)": text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              count(CASE WHEN c.clicked_at >= :cur_start AND c.clicked_at <= :cur_end THEN 1 END) AS current_clicks,
              count(CASE WHEN c.clicked_at >= :prev_start AND c.clicked_at < :prev_end THEN 1 END) AS previous_clicks
            FROM click_events c
            WHERE c.link_id = :link_id
              AND c.clicked_at >= :prev_start
              AND c.clicked_at <= :cur_end;
        """),
        "1b. Summary (All Links for User)": text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              count(CASE WHEN c.clicked_at >= :cur_start AND c.clicked_at <= :cur_end THEN 1 END) AS current_clicks,
              count(CASE WHEN c.clicked_at >= :prev_start AND c.clicked_at < :prev_end THEN 1 END) AS previous_clicks
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :prev_start
              AND c.clicked_at <= :cur_end;
        """),
        "2a. Timeseries (Single Link)": text(f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              {binary_case_expr} AS day,
              count(c.id) AS click_count
            FROM click_events c
            WHERE c.link_id = :link_id
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY 1 ASC;
        """),
        "2b. Timeseries (All Links for User)": text(f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              {binary_case_expr} AS day,
              count(c.id) AS click_count
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY 1 ASC;
        """),
        "3. Top Links": text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              l.id,
              l.short_code,
              l.original_url,
              count(c.id) AS click_count
            FROM links l
            JOIN click_events c ON l.id = c.link_id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY l.id, l.short_code, l.original_url
            ORDER BY click_count DESC, l.id ASC
            LIMIT :limit;
        """),
        "4a. Breakdown Referrers (All Links)": text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              CASE
                WHEN c.referrer IS NULL OR trim(c.referrer) = '' THEN 'Direct'
                ELSE split_part(regexp_replace(c.referrer, '^https?://', '', 'i'), '/', 1)
              END AS host_ref,
              count(c.id) AS click_count
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY click_count DESC, host_ref ASC;
        """),
        "4b. Breakdown Devices (All Links)": text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT
              coalesce(c.device_type, 'unknown') AS device_type,
              count(c.id) AS click_count
            FROM click_events c
            JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :user_id
              AND l.deleted_at IS NULL
              AND c.clicked_at >= :cur_start
              AND c.clicked_at <= :cur_end
            GROUP BY 1
            ORDER BY click_count DESC, device_type ASC;
        """),
    }

    with engine.connect() as conn:
        for name, query in queries.items():
            print(f"\n{'='*70}\n{name}\n{'='*70}")
            result = conn.execute(query, params).fetchall()
            for row in result:
                print(row[0])

if __name__ == "__main__":
    run_plans()

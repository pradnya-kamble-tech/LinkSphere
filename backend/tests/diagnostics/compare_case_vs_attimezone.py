import os, sys
sys.path.insert(0, os.path.abspath("."))
import time
from sqlalchemy import create_engine, text
from app.analytics.service import calculate_range_boundaries, build_binary_case

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
engine = create_engine(TEST_DB_URL)

bounds = calculate_range_boundaries(30, "America/New_York")
binary_case_expr = build_binary_case(bounds["day_ranges"])
cur_start = bounds["current_start_utc"]
cur_end = bounds["current_end_utc"]

# 1. 20-link user
uid_20 = "fd12a248-e232-4ffc-b12f-892285f15f05"

def run_compare():
    with engine.connect() as conn:
        print("=== 20-LINK USER COMPARISON ===")
        # CASE bucketing
        q_case = text(f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT {binary_case_expr} AS day, count(c.id) AS click_count
            FROM click_events c JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :uid AND l.deleted_at IS NULL AND c.clicked_at >= :s AND c.clicked_at <= :e
            GROUP BY 1 ORDER BY 1 ASC;
        """)
        res_case_20 = conn.execute(q_case, {"uid": uid_20, "s": cur_start, "e": cur_end}).fetchall()
        time_case_20 = [r[0] for r in res_case_20 if "Execution Time" in r[0]][0]

        # AT TIME ZONE
        q_tz = text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT (c.clicked_at AT TIME ZONE :tz)::date AS day, count(c.id) AS click_count
            FROM click_events c JOIN links l ON c.link_id = l.id
            WHERE l.user_id = :uid AND l.deleted_at IS NULL AND c.clicked_at >= :s AND c.clicked_at <= :e
            GROUP BY 1 ORDER BY 1 ASC;
        """)
        res_tz_20 = conn.execute(q_tz, {"uid": uid_20, "tz": "America/New_York", "s": cur_start, "e": cur_end}).fetchall()
        time_tz_20 = [r[0] for r in res_tz_20 if "Execution Time" in r[0]][0]

        print(f"CASE Bucketing (20 links): {time_case_20}")
        print(f"AT TIME ZONE   (20 links): {time_tz_20}")

        # 1,000 links simulation (querying across links 41 to 1040)
        print("\n=== 1,000-LINK USER COMPARISON ===")
        q_case_1000 = text(f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT {binary_case_expr} AS day, count(c.id) AS click_count
            FROM click_events c
            WHERE c.link_id >= 41 AND c.link_id <= 1040 AND c.clicked_at >= :s AND c.clicked_at <= :e
            GROUP BY 1 ORDER BY 1 ASC;
        """)
        res_case_1000 = conn.execute(q_case_1000, {"s": cur_start, "e": cur_end}).fetchall()
        time_case_1000 = [r[0] for r in res_case_1000 if "Execution Time" in r[0]][0]

        q_tz_1000 = text("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT (c.clicked_at AT TIME ZONE :tz)::date AS day, count(c.id) AS click_count
            FROM click_events c
            WHERE c.link_id >= 41 AND c.link_id <= 1040 AND c.clicked_at >= :s AND c.clicked_at <= :e
            GROUP BY 1 ORDER BY 1 ASC;
        """)
        res_tz_1000 = conn.execute(q_tz_1000, {"tz": "America/New_York", "s": cur_start, "e": cur_end}).fetchall()
        time_tz_1000 = [r[0] for r in res_tz_1000 if "Execution Time" in r[0]][0]

        print(f"CASE Bucketing (1,000 links): {time_case_1000}")
        print(f"AT TIME ZONE   (1,000 links): {time_tz_1000}")

if __name__ == "__main__":
    run_compare()

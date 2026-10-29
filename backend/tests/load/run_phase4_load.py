import os
import sys
import time
import json
import csv
import subprocess
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
from tests.load.seed_phase4_data import seed_phase4_heavy_data

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
assert TEST_DB_URL.endswith("_test"), "ABORT: Not test DB"


def parse_locust_stats(csv_prefix):
    stats_file = f"{csv_prefix}_stats.csv"
    results = []
    if os.path.exists(stats_file):
        with open(stats_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(row)
    return results


def run_locust_single(env, user_class, users, run_time_sec, host, csv_prefix):
    locust_file = os.path.join(os.path.dirname(__file__), "locustfile.py")
    cmd = [
        sys.executable,
        "-m", "locust",
        "-f", locust_file,
        "--headless",
        "--users", str(users),
        "--spawn-rate", str(min(users, 50)),
        "--run-time", f"{run_time_sec}s",
        "--host", host,
        "--csv", csv_prefix,
        user_class,
    ]
    p = subprocess.Popen(
        cmd,
        cwd=backend_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    p.wait()
    return parse_locust_stats(csv_prefix)


def main():
    print("=== STARTING PHASE 4 LOAD TEST BENCHMARK ===")
    user_id, token, redir_link_id = seed_phase4_heavy_data()
    print(f"Seeded User ID: {user_id}, Redir Link ID: {redir_link_id}")

    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["ENVIRONMENT"] = "test"
    env["DATABASE_URL"] = TEST_DB_URL
    env["LOAD_TEST_HEAVY_TOKEN"] = token

    # Start FastAPI server on port 8028 without --reload
    srv_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8028", "--log-level", "warning"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)

    try:
        results = {}

        # 1. db-ping SELECT 1 baseline
        print("\n[1/4] Running db-ping SELECT 1 (50 users, 15s)...")
        csv_db = os.path.join(os.path.dirname(__file__), "phase4_db_ping")
        stats_db = run_locust_single(env, "DiagnosticDbPingUser", 50, 15, "http://127.0.0.1:8028", csv_db)
        results["db_ping"] = stats_db

        # 2. redirect on redir50
        print("\n[2/4] Running Redirect GET /redir50 (50 users, 30s)...")
        # Ensure redir50 exists and clear prior clicks
        db = SessionLocal()
        redir_link = db.query(Link).filter_by(short_code="redir50").first()
        if not redir_link:
            redir_link = Link(
                user_id=user_id,
                short_code="redir50",
                original_url="https://example.com/redirect-dest",
                is_active=True,
            )
            db.add(redir_link)
            db.commit()
            db.refresh(redir_link)
        else:
            redir_link.is_active = True
            redir_link.deleted_at = None
            db.commit()

        db.execute(text("DELETE FROM click_events WHERE link_id = :lid"), {"lid": redir_link.id})
        db.commit()
        redir_link_id = redir_link.id
        db.close()

        csv_redir = os.path.join(os.path.dirname(__file__), "phase4_redirect")
        stats_redir = run_locust_single(env, "RedirectLinkUser", 50, 30, "http://127.0.0.1:8028", csv_redir)
        results["redirect"] = stats_redir

        # Wait up to 5s for background click recording tasks to finish writing
        time.sleep(5)
        db = SessionLocal()
        actual_clicks = db.execute(select(func.count(ClickEvent.id)).where(ClickEvent.link_id == redir_link_id)).scalar() or 0
        db.close()

        # Find 302 request count from locust stats
        redir_req_row = next((r for r in stats_redir if r.get("Name") == "GET /{short_code} [Redirect 302]"), {})
        total_302s = int(redir_req_row.get("Request Count", 0))
        failures_302 = int(redir_req_row.get("Failure Count", 0))

        print(f"  -> Redirect Requests: {total_302s}, Failures: {failures_302}, Actual Click Events Recorded: {actual_clicks}")
        click_match = (total_302s == actual_clicks and failures_302 == 0)
        results["click_audit"] = {
            "redirect_302_count": total_302s,
            "recorded_clicks": actual_clicks,
            "failures": failures_302,
            "exact_match": click_match,
        }

        # 3. POST /api/links
        print("\n[3/4] Running POST /api/links (50 users, 15s)...")
        csv_post = os.path.join(os.path.dirname(__file__), "phase4_post_link")
        stats_post = run_locust_single(env, "PostLinkUser", 50, 15, "http://127.0.0.1:8028", csv_post)
        results["post_link"] = stats_post

        # 4. GET /api/links (heavy user: 1,000 links + 100,000 clicks)
        print("\n[4/4] Running GET /api/links heavy user (50 users, 15s)...")
        csv_get = os.path.join(os.path.dirname(__file__), "phase4_get_links")
        stats_get = run_locust_single(env, "GetLinksHeavyUser", 50, 15, "http://127.0.0.1:8028", csv_get)
        results["get_links"] = stats_get

        # Save raw JSON
        json_out = os.path.join(os.path.dirname(__file__), "diagnostics_results_phase4.json")
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        # Build Markdown report
        db_ping_row = next((r for r in stats_db if r.get("Name") == "GET /api/diagnostic/db-ping [SELECT 1]"), {})
        db_p95 = float(db_ping_row.get("95%", 0.0)) if db_ping_row.get("95%") else 1.0

        md_out = os.path.join(os.path.dirname(__file__), "results_phase4.md")
        with open(md_out, "w", encoding="utf-8") as f:
            f.write("# Phase 4 Load Test & Performance Baselines\n\n")
            f.write("> **Setup**: 50 Concurrent Users, 15s duration per test, single worker without `--reload`, target database `linksphere_test`.\n\n")

            f.write("## 1. Phase 4 Endpoints & Ratio Relative to `db-ping` (`SELECT 1`)\n\n")
            f.write(f"* **`db-ping` (`SELECT 1`) Baseline p95**: **{db_p95} ms** (Throughput: {db_ping_row.get('Requests/s', 'N/A')} req/s)\n\n")

            f.write("| Endpoint | Request Count | Failures | Req/s | Median (ms) | p95 (ms) | p99 (ms) | Ratio vs db-ping p95 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")

            all_runs = [
                ("GET /api/diagnostic/db-ping [SELECT 1]", stats_db),
                ("GET /{short_code} [Redirect 302]", stats_redir),
                ("POST /api/links [Create Link]", stats_post),
                ("GET /api/links [1000 Links + 100k Clicks]", stats_get),
            ]

            for name, stat_list in all_runs:
                row = next((r for r in stat_list if r.get("Name") == name), {})
                p95_val = float(row.get("95%", 0.0)) if row.get("95%") else 0.0
                ratio = round(p95_val / db_p95, 2) if db_p95 > 0 else "N/A"
                f.write(f"| `{name}` | {row.get('Request Count', 'N/A')} | {row.get('Failure Count', 'N/A')} | {row.get('Requests/s', 'N/A')} | {row.get('50%', 'N/A')} | **{p95_val}** | {row.get('99%', 'N/A')} | **{ratio}x** |\n")

            f.write("\n## 2. Redirect Click Audit\n\n")
            f.write(f"- **302 Redirect Responses Delivered**: {total_302s}\n")
            f.write(f"- **Click Events Recorded in Database**: {actual_clicks}\n")
            f.write(f"- **Redirect Failures / Dropped Requests**: {failures_302}\n")
            f.write(f"- **Exact Match (302 Count == Click Count & 0 Errors)**: **{'PASS' if click_match else 'FAIL'}**\n")

        print(f"\nSaved Phase 4 report to {md_out}")

    finally:
        srv_proc.terminate()
        srv_proc.wait()
        # Clean up locust CSVs
        for pfx in ["phase4_db_ping", "phase4_redirect", "phase4_post_link", "phase4_get_links"]:
            for ext in ["_stats.csv", "_stats_history.csv", "_failures.csv", "_exceptions.csv"]:
                f_p = os.path.join(os.path.dirname(__file__), pfx + ext)
                if os.path.exists(f_p):
                    try:
                        os.remove(f_p)
                    except Exception:
                        pass
        print("FastAPI server stopped and temporary CSVs cleaned up.")


if __name__ == "__main__":
    main()

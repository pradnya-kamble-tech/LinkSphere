import os
import sys
import time
import json
import csv
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Ensure we run strictly against linksphere_test
TEST_DB_NAME = "linksphere_test"
assert TEST_DB_NAME.endswith("_test"), "ABORT: Target is not a test database!"
TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import all models to ensure mapper initialization
import app.users.models
import app.auth.models
import app.links.models
import app.analytics.models
from app.users.models import User
from app.auth.service import create_user_session

engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# Seed user for valid session test
valid_user = db.query(User).filter_by(email="loadtest_valid@example.com").first()
if not valid_user:
    valid_user = User(email="loadtest_valid@example.com", name="Load Valid User")
    db.add(valid_user)
    db.commit()

logout_user = db.query(User).filter_by(email="loadtest_logout@example.com").first()
if not logout_user:
    logout_user = User(email="loadtest_logout@example.com", name="Load Logout User")
    db.add(logout_user)
    db.commit()

valid_user_id = valid_user.id
logout_user_id = logout_user.id
valid_token, _ = create_user_session(db, valid_user_id)
logout_token, _ = create_user_session(db, logout_user_id)
db.close()

# Prepare environment for test server & locust
env = os.environ.copy()
env["DATABASE_URL"] = TEST_DB_URL
env["ENVIRONMENT"] = "test"
env["GOOGLE_CLIENT_ID"] = "test_google"
env["GOOGLE_CLIENT_SECRET"] = "test_google_secret"
env["GITHUB_CLIENT_ID"] = "test_github"
env["GITHUB_CLIENT_SECRET"] = "test_github_secret"
env["SESSION_SECRET"] = "test_session_secret_32_bytes_ok"
env["LOAD_TEST_VALID_TOKEN"] = valid_token
env["LOAD_TEST_LOGOUT_TOKEN"] = logout_token

server_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8009", "--log-level", "warning"],
    cwd=backend_dir,
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(2)

try:
    with urllib.request.urlopen("http://127.0.0.1:8009/api/health", timeout=5) as r:
        assert r.status == 200
        print("Test server active on http://127.0.0.1:8009")

    results_data = {}

    for users in [50, 200]:
        print(f"\n--- Running Load Test with {users} Concurrent Users ---")
        # Generate fresh tokens for each load run
        db = SessionLocal()
        run_valid_token, _ = create_user_session(db, valid_user_id)
        run_logout_token, _ = create_user_session(db, logout_user_id)
        db.close()
        env["LOAD_TEST_VALID_TOKEN"] = run_valid_token
        env["LOAD_TEST_LOGOUT_TOKEN"] = run_logout_token

        csv_prefix = os.path.join(os.path.dirname(__file__), f"locust_{users}")
        cmd = [
            sys.executable,
            "-m",
            "locust",
            "-f",
            os.path.join(os.path.dirname(__file__), "locustfile.py"),
            "--headless",
            "-u",
            str(users),
            "-r",
            str(min(users, 50)),
            "--run-time",
            "15s",
            "--host",
            "http://127.0.0.1:8009",
            "--csv",
            csv_prefix,
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        print(res.stderr)
        time.sleep(1)

        stats_csv = f"{csv_prefix}_stats.csv"
        if os.path.exists(stats_csv):
            with open(stats_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                results_data[f"users_{users}"] = list(reader)

    # Save JSON summary
    out_json = os.path.join(os.path.dirname(__file__), "results_phase3.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)

    # Save Markdown summary
    out_md = os.path.join(os.path.dirname(__file__), "results_phase3.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# Phase 3 Load Test Results\n\n")
        f.write("> **Note**: Local machine baseline numbers, not production capacity.\n\n")
        for key, rows in results_data.items():
            f.write(f"## {key.replace('_', ' ').title()}\n\n")
            f.write("| Endpoint / Task | Requests | Failures | Req/s | p50 (ms) | p95 (ms) | p99 (ms) |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for row in rows:
                name = row.get("Name", "")
                reqs = row.get("Request Count", "0")
                fails = row.get("Failure Count", "0")
                rps = row.get("Requests/s", "0.0")
                p50 = row.get("50%", "N/A")
                p95 = row.get("95%", "N/A")
                p99 = row.get("99%", "N/A")
                f.write(f"| {name} | {reqs} | {fails} | {rps} | {p50} | {p95} | {p99} |\n")
            f.write("\n")

    print(f"\nSaved load test metrics to {out_json} and {out_md}")

finally:
    server_proc.terminate()
    server_proc.wait()
    print("Test server stopped cleanly.")

import os
import sys
import time
import json
import csv
import subprocess
import urllib.request
import threading
import psutil

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_NAME = "linksphere_test"
assert TEST_DB_NAME.endswith("_test"), "ABORT: Target is not a test database!"
TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import app.users.models
import app.auth.models
import app.links.models
import app.analytics.models
from app.users.models import User
from app.auth.models import AuthIdentity, Session
from app.auth.service import create_user_session

engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def seed_users():
    db = SessionLocal()
    # 1. Valid user
    valid_user = db.query(User).filter_by(email="loadtest_valid@example.com").first()
    if not valid_user:
        valid_user = User(email="loadtest_valid@example.com", name="Load Valid User")
        db.add(valid_user)
        db.commit()

    # 2. Logout user
    logout_user = db.query(User).filter_by(email="loadtest_logout@example.com").first()
    if not logout_user:
        logout_user = User(email="loadtest_logout@example.com", name="Load Logout User")
        db.add(logout_user)
        db.commit()

    # 3. Returning user
    ret_user = db.query(User).filter_by(email="loadtest_returning@example.com").first()
    if not ret_user:
        ret_user = User(email="loadtest_returning@example.com", name="Load Returning User")
        db.add(ret_user)
        db.commit()
    ret_ident = db.query(AuthIdentity).filter_by(provider="google", provider_user_id="google-returning-load-sub").first()
    if not ret_ident:
        ret_ident = AuthIdentity(user_id=ret_user.id, provider="google", provider_user_id="google-returning-load-sub", email_verified=True)
        db.add(ret_ident)
        db.commit()

    valid_token, _ = create_user_session(db, valid_user.id)
    logout_token, _ = create_user_session(db, logout_user.id)
    v_id = valid_user.id
    l_id = logout_user.id
    db.close()
    return v_id, l_id, valid_token, logout_token

def get_cpu_stats(server_proc, locust_pid, postgres_name="linksphere-v2-db"):
    try:
        sys_cpu = psutil.cpu_percent(interval=None)
        server_cpu = 0.0
        if server_proc and psutil.pid_exists(server_proc.pid):
            p = psutil.Process(server_proc.pid)
            server_cpu += p.cpu_percent()
            for child in p.children(recursive=True):
                server_cpu += child.cpu_percent()
        
        locust_cpu = 0.0
        if locust_pid and psutil.pid_exists(locust_pid):
            lp = psutil.Process(locust_pid)
            locust_cpu += lp.cpu_percent()
            for child in lp.children(recursive=True):
                locust_cpu += child.cpu_percent()

        return {"system_cpu": sys_cpu, "server_cpu": round(server_cpu, 1), "locust_cpu": round(locust_cpu, 1)}
    except Exception:
        return {"system_cpu": 0, "server_cpu": 0, "locust_cpu": 0}

def run_locust_run(env, user_classes, users, spawn_rate, duration_sec, host, csv_prefix):
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
        str(spawn_rate),
        "--run-time",
        f"{duration_sec}s",
        "--host",
        host,
        "--csv",
        csv_prefix,
    ]
    if user_classes:
        cmd.extend(user_classes)

    locust_proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    
    # Sample CPU during run
    cpu_records = []
    end_t = time.time() + duration_sec
    while time.time() < end_t and locust_proc.poll() is None:
        cpu_records.append(get_cpu_stats(None, locust_proc.pid))
        time.sleep(1)

    stderr = locust_proc.communicate()[1].decode("utf-8")
    
    stats = []
    stats_csv = f"{csv_prefix}_stats.csv"
    if os.path.exists(stats_csv):
        with open(stats_csv, "r", encoding="utf-8") as f:
            stats = list(csv.DictReader(f))

    avg_locust_cpu = round(sum(r["locust_cpu"] for r in cpu_records) / len(cpu_records), 1) if cpu_records else 0.0
    avg_sys_cpu = round(sum(r["system_cpu"] for r in cpu_records) / len(cpu_records), 1) if cpu_records else 0.0

    return stats, avg_locust_cpu, avg_sys_cpu

def main():
    print("=== STARTING COMPREHENSIVE PHASE 3 DIAGNOSTIC & LOAD RUN ===")
    v_id, l_id, valid_token, logout_token = seed_users()

    # Base environment
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DB_URL
    env["ENVIRONMENT"] = "test"
    env["GOOGLE_CLIENT_ID"] = "test_google"
    env["GOOGLE_CLIENT_SECRET"] = "test_google_secret"
    env["GOOGLE_TOKEN_URL"] = "http://127.0.0.1:8010/token"
    env["GOOGLE_CERTS_URL"] = "http://127.0.0.1:8010/certs"
    env["SESSION_SECRET"] = "test_session_secret_32_bytes_long_ok"
    env["DB_POOL_SIZE"] = "10"
    env["DB_MAX_OVERFLOW"] = "10"
    env["DB_POOL_TIMEOUT"] = "30"
    env["LOAD_TEST_VALID_TOKEN"] = valid_token
    env["LOAD_TEST_LOGOUT_TOKEN"] = logout_token

    # 1. Start mock OAuth provider on port 8010
    print("[1/5] Starting mock OAuth provider on 127.0.0.1:8010...")
    mock_proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "mock_provider.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)

    all_diagnostics = {}

    try:
        # =========================================================================
        # EXPERIMENT 1: NO-DB TRIVIAL BASELINES (Async vs Sync Threadpool)
        # =========================================================================
        print("\n[2/5] Running No-DB Trivial Baselines (1 Worker)...")
        srv_trivial = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8021", "--log-level", "warning"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        trivial_results = {}
        for users in [50, 200]:
            print(f"  -> Testing No-DB Async Ping with {users} users...")
            csv_p = os.path.join(os.path.dirname(__file__), f"diag_async_{users}")
            stats, l_cpu, s_cpu = run_locust_run(env, ["DiagnosticPingAsyncUser"], users, min(users, 50), 10, "http://127.0.0.1:8021", csv_p)
            trivial_results[f"async_{users}"] = {"stats": stats, "locust_cpu": l_cpu, "sys_cpu": s_cpu}

            print(f"  -> Testing No-DB Sync Ping with {users} users...")
            csv_p = os.path.join(os.path.dirname(__file__), f"diag_sync_{users}")
            stats, l_cpu, s_cpu = run_locust_run(env, ["DiagnosticPingSyncUser"], users, min(users, 50), 10, "http://127.0.0.1:8021", csv_p)
            trivial_results[f"sync_{users}"] = {"stats": stats, "locust_cpu": l_cpu, "sys_cpu": s_cpu}

        srv_trivial.terminate()
        srv_trivial.wait()
        all_diagnostics["trivial_baselines"] = trivial_results

        # =========================================================================
        # EXPERIMENT 2: 1 WORKER RUN (Full Auth Suite)
        # =========================================================================
        print("\n[3/5] Running Core Auth Suite on 1 WORKER (50 and 200 users)...")
        srv_1w = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8022", "--log-level", "warning"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        core_classes = ["ValidSessionUser", "InvalidSessionUser", "LogoutUser", "CallbackReturningUser", "CallbackNewUser"]
        results_1w = {}
        for users in [50, 200]:
            print(f"  -> 1 Worker with {users} users...")
            # Refresh tokens
            db = SessionLocal()
            run_valid_token, _ = create_user_session(db, v_id)
            run_logout_token, _ = create_user_session(db, l_id)
            db.close()
            env["LOAD_TEST_VALID_TOKEN"] = run_valid_token
            env["LOAD_TEST_LOGOUT_TOKEN"] = run_logout_token

            csv_p = os.path.join(os.path.dirname(__file__), f"core_1w_{users}")
            stats, l_cpu, s_cpu = run_locust_run(env, core_classes, users, min(users, 50), 15, "http://127.0.0.1:8022", csv_p)
            results_1w[f"users_{users}"] = {"stats": stats, "locust_cpu": l_cpu, "sys_cpu": s_cpu}

        srv_1w.terminate()
        srv_1w.wait()
        all_diagnostics["worker_1"] = results_1w

        # =========================================================================
        # EXPERIMENT 3: MULTI-WORKER RUN (4 Workers, Full Auth Suite)
        # =========================================================================
        print("\n[4/5] Running Core Auth Suite on 4 WORKERS (50 and 200 users)...")
        srv_4w = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8024", "--workers", "4", "--log-level", "warning"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)

        results_4w = {}
        for users in [50, 200]:
            print(f"  -> 4 Workers with {users} users...")
            # Refresh tokens
            db = SessionLocal()
            run_valid_token, _ = create_user_session(db, v_id)
            run_logout_token, _ = create_user_session(db, l_id)
            db.close()
            env["LOAD_TEST_VALID_TOKEN"] = run_valid_token
            env["LOAD_TEST_LOGOUT_TOKEN"] = run_logout_token

            csv_p = os.path.join(os.path.dirname(__file__), f"core_4w_{users}")
            stats, l_cpu, s_cpu = run_locust_run(env, core_classes, users, min(users, 50), 15, "http://127.0.0.1:8024", csv_p)
            results_4w[f"users_{users}"] = {"stats": stats, "locust_cpu": l_cpu, "sys_cpu": s_cpu}

        srv_4w.terminate()
        srv_4w.wait()
        all_diagnostics["worker_4"] = results_4w

        # =========================================================================
        # EXPERIMENT 4: THROTTLING last_seen_at (MEASURED COMPARISON)
        # =========================================================================
        print("\n[5/5] Measuring last_seen_at Throttling Impact...")
        # We test /api/me alone under 50 users:
        # Case 1: Throttled (standard get_valid_session with 5-minute skip)
        print("  -> Measuring Throttled reads (5-min window)...")
        srv_th = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8025", "--log-level", "warning"],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        csv_th = os.path.join(os.path.dirname(__file__), "throttle_active_50")
        stats_th, _, _ = run_locust_run(env, ["ValidSessionUser"], 50, 50, 10, "http://127.0.0.1:8025", csv_th)
        srv_th.terminate()
        srv_th.wait()

        all_diagnostics["throttling_comparison"] = {
            "throttled": stats_th,
        }

        # Save all raw diagnostics to JSON
        diag_out = os.path.join(os.path.dirname(__file__), "diagnostics_results.json")
        with open(diag_out, "w", encoding="utf-8") as f:
            json.dump(all_diagnostics, f, indent=2)
        print(f"\nSaved raw diagnostics to {diag_out}")

        # Save Phase 3 Markdown Report
        md_out = os.path.join(os.path.dirname(__file__), "results_phase3.md")
        with open(md_out, "w", encoding="utf-8") as f:
            f.write("# Phase 3 Load Test & Diagnostics Results\n\n")
            f.write("> **Environment**: Local Windows Laptop (Intel/AMD multi-core, PostgreSQL on Docker host port 5434).\n\n")

            f.write("## 1. Approved Thresholds vs Actual Results\n\n")
            f.write("| Endpoint / Scenario | Concurrency | Approved Threshold | Actual p95 (1 Worker) | Actual p95 (4 Workers) | Result |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")

            # Threshold lookup
            thresholds = {
                "GET /api/me [Valid Session]": 50,
                "POST /api/auth/logout": 50,
                "GET /api/me [Invalid/Forged 401]": 30,
                "GET /api/auth/callback/google [New User]": 100,
                "GET /api/auth/callback/google [Returning User]": 100,
            }

            for u_key in ["users_50", "users_200"]:
                u_count = 50 if "50" in u_key else 200
                rows_1w = {r.get("Name"): r for r in results_1w.get(u_key, {}).get("stats", [])}
                rows_4w = {r.get("Name"): r for r in results_4w.get(u_key, {}).get("stats", [])}
                for ep_name, thresh in thresholds.items():
                    p95_1 = rows_1w.get(ep_name, {}).get("95%", "N/A")
                    p95_4 = rows_4w.get(ep_name, {}).get("95%", "N/A")
                    res = "PASS" if (p95_4 != "N/A" and float(p95_4) < thresh) else "FAIL"
                    f.write(f"| `{ep_name}` | {u_count} users | p95 < {thresh}ms | {p95_1} ms | {p95_4} ms | **{res}** |\n")

            f.write("\n## 2. Framework vs Database Diagnosis (Trivial Baselines)\n\n")
            f.write("| Scenario | Users | Req/s | Median (ms) | p95 (ms) | p99 (ms) |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for k, d in trivial_results.items():
                for r in d.get("stats", []):
                    if r.get("Name") and r.get("Name") != "Aggregated":
                        f.write(f"| {r.get('Name')} | {k} | {r.get('Requests/s')} | {r.get('50%')} | {r.get('95%')} | {r.get('99%')} |\n")

            f.write("\n## 3. Worker Concurrency: 1 Worker vs 4 Workers\n\n")
            f.write("### 50 Concurrent Users\n\n")
            f.write("| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            r1 = {r.get("Name"): r for r in results_1w.get("users_50", {}).get("stats", [])}
            r4 = {r.get("Name"): r for r in results_4w.get("users_50", {}).get("stats", [])}
            for name in r1:
                if name:
                    f.write(f"| `{name}` | {r1[name].get('Requests/s')} | {r1[name].get('95%')} ms | {r4.get(name, {}).get('Requests/s', 'N/A')} | {r4.get(name, {}).get('95%', 'N/A')} ms |\n")

            f.write("\n### 200 Concurrent Users\n\n")
            f.write("| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            r1_200 = {r.get("Name"): r for r in results_1w.get("users_200", {}).get("stats", [])}
            r4_200 = {r.get("Name"): r for r in results_4w.get("users_200", {}).get("stats", [])}
            for name in r1_200:
                if name:
                    f.write(f"| `{name}` | {r1_200[name].get('Requests/s')} | {r1_200[name].get('95%')} ms | {r4_200.get(name, {}).get('Requests/s', 'N/A')} | {r4_200.get(name, {}).get('95%', 'N/A')} ms |\n")

            f.write("\n## 4. CPU Utilization Profiling\n\n")
            f.write("| Run Scenario | Server Workers | Locust CPU % | System CPU % |\n")
            f.write("| :--- | :--- | :--- | :--- |\n")
            f.write(f"| 50 Users Core Auth | 1 Worker | {results_1w.get('users_50', {}).get('locust_cpu')}% | {results_1w.get('users_50', {}).get('sys_cpu')}% |\n")
            f.write(f"| 200 Users Core Auth | 1 Worker | {results_1w.get('users_200', {}).get('locust_cpu')}% | {results_1w.get('users_200', {}).get('sys_cpu')}% |\n")
            f.write(f"| 50 Users Core Auth | 4 Workers | {results_4w.get('users_50', {}).get('locust_cpu')}% | {results_4w.get('users_50', {}).get('sys_cpu')}% |\n")
            f.write(f"| 200 Users Core Auth | 4 Workers | {results_4w.get('users_200', {}).get('locust_cpu')}% | {results_4w.get('users_200', {}).get('sys_cpu')}% |\n")

        print(f"Saved Phase 3 Markdown Report to {md_out}")

    finally:
        mock_proc.terminate()
        mock_proc.wait()
        print("Mock OAuth provider stopped cleanly.")

if __name__ == "__main__":
    main()

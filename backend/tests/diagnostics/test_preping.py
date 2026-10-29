import os
import sys
import time
import subprocess

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from tests.load.run_phase4_load import run_locust_single

def benchmark_db_ping(pre_ping: bool):
    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["ENVIRONMENT"] = "test"
    env["DB_POOL_PRE_PING"] = str(pre_ping).lower()
    env["DATABASE_URL"] = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
    
    port = 8035 if pre_ping else 8036
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    try:
        csv_pfx = os.path.join(os.path.dirname(__file__), f"db_ping_preping_{pre_ping}")
        stats = run_locust_single(env, "DiagnosticDbPingUser", 50, 15, f"http://127.0.0.1:{port}", csv_pfx)
        row = next((r for r in stats if "DiagnosticDbPingUser" in r.get("Name") or "SELECT 1" in r.get("Name")), {})
        return row
    finally:
        srv.terminate()
        srv.wait()
        for ext in ["_stats.csv", "_stats_history.csv", "_failures.csv", "_exceptions.csv"]:
            f = f"{csv_pfx}{ext}"
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    row_on = benchmark_db_ping(True)
    row_off = benchmark_db_ping(False)
    print("--- db-ping with pool_pre_ping=True ---")
    print(f"Req/s: {row_on.get('Requests/s')}, Median: {row_on.get('50%')} ms, p95: {row_on.get('95%')} ms")
    print("--- db-ping with pool_pre_ping=False ---")
    print(f"Req/s: {row_off.get('Requests/s')}, Median: {row_off.get('50%')} ms, p95: {row_off.get('95%')} ms")

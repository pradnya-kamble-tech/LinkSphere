import os
import sys
import time
import asyncio
import subprocess
import httpx
from sqlalchemy import create_engine, text

backend_dir = os.path.abspath(".")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
SERVER_PORT = 8060

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

def check_db_and_analyze():
    engine = create_engine(TEST_DB_URL)
    with engine.connect() as conn:
        print("Running manual ANALYZE on all test tables...")
        conn.execute(text("ANALYZE click_events; ANALYZE links; ANALYZE users; ANALYZE sessions;"))
        conn.commit()

        # Wait until autovacuum workers are idle
        while True:
            active_vac = conn.execute(text("""
                SELECT count(*) FROM pg_stat_activity 
                WHERE (query ILIKE '%vacuum%' OR query ILIKE '%analyze%') 
                  AND pid != pg_backend_pid();
            """)).scalar()
            print(f"Active vacuum/analyze workers in PostgreSQL: {active_vac}")
            if active_vac == 0:
                break
            time.sleep(1)
        print("PostgreSQL background vacuum/analyze workers are idle.")

async def benchmark_typical_summary():
    check_db_and_analyze()

    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["ENVIRONMENT"] = "test"
    env["DATABASE_URL"] = TEST_DB_URL

    srv_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT), "--log-level", "warning"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    typical_token = "typical_phase6_session_token_1234567890"
    url_path = "/api/analytics/summary?range=30&tz=UTC"
    concurrency = 50
    duration_s = 15

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(30.0)

    stop_time = time.time() + duration_s
    latencies = []
    status_counts = {}
    completed_requests = 0

    print(f"\n--- Running benchmark on {url_path} (Typical User, 1 Worker, 50 Users, 15s) ---")

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{SERVER_PORT}", limits=limits, timeout=timeout) as client:
            # Warm up
            resp = await client.get("/health")
            assert resp.status_code == 200

            async def worker():
                nonlocal completed_requests
                headers = {"Cookie": f"session_token={typical_token}"}
                while time.time() < stop_time:
                    t0 = time.time()
                    try:
                        r = await client.get(url_path, headers=headers)
                        t_req = (time.time() - t0) * 1000.0
                        latencies.append(t_req)
                        status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                        completed_requests += 1
                    except Exception as e:
                        status_counts[f"err_{type(e).__name__}"] = status_counts.get(f"err_{type(e).__name__}", 0) + 1
                    await asyncio.sleep(0.001)

            t_start = time.time()
            tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
            await asyncio.gather(*tasks)
            elapsed = time.time() - t_start

        rps = completed_requests / elapsed if elapsed > 0 else 0
        p50 = calc_p(latencies, 50)
        p95 = calc_p(latencies, 95)
        p99 = calc_p(latencies, 99)

        print(f"\nBenchmark Results:")
        print(f"  Total Requests: {completed_requests} in {elapsed:.2f}s")
        print(f"  Throughput:     {rps:.1f} req/s")
        print(f"  p50 latency:    {p50:.2f} ms")
        print(f"  p95 latency:    {p95:.2f} ms")
        print(f"  p99 latency:    {p99:.2f} ms")
        print(f"  Status codes:   {status_counts}")
    finally:
        srv_proc.terminate()
        srv_proc.wait()

if __name__ == "__main__":
    asyncio.run(benchmark_typical_summary())

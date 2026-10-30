import os
import sys
import time
import asyncio
import subprocess
import httpx
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
SERVER_PORT = 8039

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

async def benchmark_endpoint(client, url_path, session_token, duration_s=15, concurrency=50):
    print(f"\n--- Benchmarking {url_path} ({concurrency} concurrent users, {duration_s}s) ---")
    stop_time = time.time() + duration_s
    latencies = []
    status_counts = {}
    completed_requests = 0

    async def worker():
        nonlocal completed_requests
        headers = {"Cookie": f"session_token={session_token}"}
        while time.time() < stop_time:
            t0 = time.time()
            try:
                resp = await client.get(url_path, headers=headers)
                t_req = (time.time() - t0) * 1000.0
                status = resp.status_code
                latencies.append(t_req)
                status_counts[status] = status_counts.get(status, 0) + 1
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

    print(f"Results for {url_path}:")
    print(f"  Total requests: {completed_requests} in {elapsed:.2f}s")
    print(f"  Throughput:     {rps:.1f} req/s")
    print(f"  p50 latency:    {p50:.2f} ms")
    print(f"  p95 latency:    {p95:.2f} ms")
    print(f"  p99 latency:    {p99:.2f} ms")
    print(f"  Status codes:   {status_counts}")

    return {
        "endpoint": url_path,
        "total_requests": completed_requests,
        "rps": round(rps, 1),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "status_codes": status_counts,
    }

async def main_async():
    print("=== STARTING PHASE 6 LOAD BENCHMARK (50 USERS, 15s PER ENDPOINT, 1M ROWS) ===")
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

    engine = create_engine(TEST_DB_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    import app.users.models  # noqa: F401
    import app.auth.models  # noqa: F401
    import app.links.models  # noqa: F401
    import app.analytics.models  # noqa: F401
    from app.users.models import User
    from app.auth.service import create_user_session

    user = db.query(User).filter_by(email="testuser@example.com").first()
    if not user:
        raise RuntimeError("testuser@example.com not found. Please run seed_multitenant_data.py first.")
    raw_token, _ = create_user_session(db, user.id)
    db.close()

    endpoints = [
        "/api/analytics/summary?range=30&tz=UTC",
        "/api/analytics/timeseries?range=30&tz=UTC",
        "/api/analytics/top-links?range=30&tz=UTC&limit=10",
        "/api/analytics/breakdown?range=30&tz=UTC",
    ]

    results = []
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(30.0)

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{SERVER_PORT}", limits=limits, timeout=timeout) as client:
            # Warm up
            resp = await client.get("/health")
            assert resp.status_code == 200, f"Health check failed: {resp.status_code}"

            for ep in endpoints:
                res = await benchmark_endpoint(client, ep, raw_token, duration_s=15, concurrency=50)
                results.append(res)
    finally:
        srv_proc.terminate()
        srv_proc.wait()

    with open("tests/load/phase6_load_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== SUMMARY OF PHASE 6 LOAD TEST ===")
    for r in results:
        print(f"{r['endpoint']}: {r['rps']} req/s | p50: {r['p50_ms']}ms | p95: {r['p95_ms']}ms | status: {r['status_codes']}")

if __name__ == "__main__":
    asyncio.run(main_async())

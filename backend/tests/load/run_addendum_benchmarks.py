import os
import sys
import time
import asyncio
import subprocess
import httpx
import json
import itertools
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

async def benchmark_endpoint(base_urls, url_path, session_token, duration_s=15, concurrency=50):
    url_cycle = itertools.cycle(base_urls)
    stop_time = time.time() + duration_s
    latencies = []
    status_counts = {}
    completed_requests = 0

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(30.0)

    async def worker():
        nonlocal completed_requests
        headers = {"Cookie": f"session_token={session_token}"}
        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            while time.time() < stop_time:
                target_url = f"{next(url_cycle)}{url_path}"
                t0 = time.time()
                try:
                    resp = await client.get(target_url, headers=headers)
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

    print(f"Results for {url_path} ({len(base_urls)} worker(s)):")
    print(f"  Total requests: {completed_requests} in {elapsed:.2f}s")
    print(f"  Throughput:     {rps:.1f} req/s")
    print(f"  p50 latency:    {p50:.2f} ms")
    print(f"  p95 latency:    {p95:.2f} ms")
    print(f"  Status codes:   {status_counts}")

    return {
        "endpoint": url_path,
        "workers": len(base_urls),
        "total_requests": completed_requests,
        "rps": round(rps, 1),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "status_codes": status_counts,
    }

async def run_all():
    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["ENVIRONMENT"] = "test"
    env["DATABASE_URL"] = TEST_DB_URL

    heavy_token = "test_phase6_session_token_1234567890"
    typical_token = "typical_phase6_session_token_1234567890"

    print("=== 1. LAUNCHING 1-WORKER SERVER ===")
    p1 = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8051", "--log-level", "warning"],
        cwd=backend_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    results = {}
    try:
        # A. Typical user (1 worker, summary & breakdown)
        print("\n--- [1 WORKER] TYPICAL USER (2,000 clicks) ---")
        results["typ_1w_summary"] = await benchmark_endpoint(["http://127.0.0.1:8051"], "/api/analytics/summary?range=30&tz=UTC", typical_token)
        results["typ_1w_breakdown"] = await benchmark_endpoint(["http://127.0.0.1:8051"], "/api/analytics/breakdown?range=30&tz=UTC", typical_token)

        # B. Heavy user breakdown with optimized single query (1 worker)
        print("\n--- [1 WORKER] HEAVY USER BREAKDOWN (OPTIMIZED GROUPING SETS) ---")
        results["heavy_1w_breakdown_opt"] = await benchmark_endpoint(["http://127.0.0.1:8051"], "/api/analytics/breakdown?range=30&tz=UTC", heavy_token)
    finally:
        p1.terminate()
        p1.wait()

    print("\n=== 2. LAUNCHING 4-WORKER CLUSTER ===")
    procs = []
    ports = [8052, 8053, 8054, 8055]
    for port in ports:
        p = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=backend_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(p)
    time.sleep(3)

    four_worker_urls = [f"http://127.0.0.1:{port}" for port in ports]
    try:
        # C. 4 Workers: Summary & Breakdown for heavy user
        print("\n--- [4 WORKERS] HEAVY USER (summary + breakdown) ---")
        results["heavy_4w_summary"] = await benchmark_endpoint(four_worker_urls, "/api/analytics/summary?range=30&tz=UTC", heavy_token)
        results["heavy_4w_breakdown"] = await benchmark_endpoint(four_worker_urls, "/api/analytics/breakdown?range=30&tz=UTC", heavy_token)
    finally:
        for p in procs:
            p.terminate()
            p.wait()

    with open("tests/load/addendum_load_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== ALL ADDENDUM BENCHMARKS COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(run_all())

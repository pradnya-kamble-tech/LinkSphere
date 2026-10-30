import os
import sys
import time
import asyncio
import subprocess
import httpx
import json
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

backend_dir = os.path.abspath(".")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
SERVER_PORT = 8065

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

async def benchmark_sessions_endpoint():
    print("=== STARTING LEVEL 7 LOAD BENCHMARK (GET /api/me/sessions, 50 USERS, 15s) ===")
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
        user = User(
            id=uuid.uuid4(),
            email="testuser@example.com",
            name="Test User",
        )
        db.add(user)
        db.commit()
    raw_token, _ = create_user_session(db, user.id)
    db.close()

    duration_s = 15
    concurrency = 50
    url_path = "/api/me/sessions"

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(30.0)

    stop_time = time.time() + duration_s
    latencies = []
    status_counts = {}
    completed_requests = 0

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{SERVER_PORT}", limits=limits, timeout=timeout) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

            async def worker():
                nonlocal completed_requests
                headers = {"Cookie": f"session_token={raw_token}"}
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

        print(f"\nLevel 7 Load Results for {url_path}:")
        print(f"  Total requests: {completed_requests} in {elapsed:.2f}s")
        print(f"  Throughput:     {rps:.1f} req/s")
        print(f"  p50 latency:    {p50:.2f} ms")
        print(f"  p95 latency:    {p95:.2f} ms")
        print(f"  p99 latency:    {p99:.2f} ms")
        print(f"  Status codes:   {status_counts}")

        result = {
            "endpoint": url_path,
            "total_requests": completed_requests,
            "rps": round(rps, 1),
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "status_codes": status_counts,
        }
        with open("tests/load/level7_load_results.json", "w") as f:
            json.dump(result, f, indent=2)
    finally:
        srv_proc.terminate()
        srv_proc.wait()

if __name__ == "__main__":
    asyncio.run(benchmark_sessions_endpoint())

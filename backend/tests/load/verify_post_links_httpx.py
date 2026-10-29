import os
import sys
import time
import asyncio
import subprocess
import httpx
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
SERVER_PORT = 8038

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

async def main_async():
    print("=== STARTING POST /api/links 50-USER 15-SECOND BENCHMARK ===")
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

    user = db.query(User).filter_by(email="post_benchmark@example.com").first()
    if not user:
        user = User(email="post_benchmark@example.com", name="Post Benchmark User")
        db.add(user)
        db.commit()
        db.refresh(user)
    raw_token, _ = create_user_session(db, user.id)
    db.close()

    base_url = f"http://127.0.0.1:{SERVER_PORT}"
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=100)
    
    total_requests = 0
    errors = 0
    latencies = []
    
    stop_event = asyncio.Event()

    async def worker(client):
        nonlocal total_requests, errors
        while not stop_event.is_set():
            slug = uuid.uuid4().hex[:8]
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    "/api/links",
                    json={"original_url": f"https://example.com/item/{slug}"},
                    headers={"Cookie": f"session_token={raw_token}", "Origin": "http://localhost:5173"},
                    timeout=10.0,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies.append(elapsed_ms)
                total_requests += 1
                if resp.status_code != 201:
                    errors += 1
            except Exception:
                errors += 1
            # Small yield to allow cooperative scheduling
            await asyncio.sleep(0.005)

    try:
        async with httpx.AsyncClient(base_url=base_url, limits=limits) as client:
            workers = [asyncio.create_task(worker(client)) for _ in range(50)]
            await asyncio.sleep(15.0)
            stop_event.set()
            await asyncio.gather(*workers)

        p50 = calc_p(latencies, 50)
        p95 = calc_p(latencies, 95)
        p99 = calc_p(latencies, 99)
        throughput = total_requests / 15.0

        print("\n--- RESULTS ---")
        print(f"Total Requests: {total_requests}")
        print(f"Errors:         {errors}")
        print(f"Throughput:     {throughput:.1f} req/s")
        print(f"p50 (Median):   {p50:.2f} ms")
        print(f"p95:            {p95:.2f} ms")
        print(f"p99:            {p99:.2f} ms")

    finally:
        srv_proc.terminate()
        srv_proc.wait()

if __name__ == "__main__":
    asyncio.run(main_async())

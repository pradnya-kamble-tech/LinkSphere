import os
import sys
import time
import asyncio
import subprocess
import httpx
from sqlalchemy import create_engine, text

def calc_p(latencies, percentile):
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * (percentile / 100.0))
    idx = min(idx, len(s) - 1)
    return s[idx]

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
SERVER_PORT = 8038


async def run_concurrent_batch_with_latencies(client, url, count, concurrency=50):
    sem = asyncio.Semaphore(concurrency)
    latencies = []
    successes = 0

    async def fetch():
        nonlocal successes
        async with sem:
            t0 = time.perf_counter()
            resp = await client.get(
                url,
                headers={"Referer": "https://news.ycombinator.com", "User-Agent": "Mozilla/5.0 (Windows NT 10.0)"},
                follow_redirects=False,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)
            if resp.status_code == 302:
                successes += 1

    tasks = [fetch() for _ in range(count)]
    await asyncio.gather(*tasks)
    return successes, latencies


async def main_async():
    print("=== STARTING ASYNCIO + HTTPX CLICK & REDIRECT VERIFICATION ===")
    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["ENVIRONMENT"] = "test"
    env["DATABASE_URL"] = TEST_DB_URL

    log_file = os.path.join(os.path.dirname(__file__), "uvicorn_real_clicks.log")
    with open(log_file, "w", encoding="utf-8") as lf:
        srv_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT), "--log-level", "info"],
            cwd=backend_dir,
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
        )

    time.sleep(3)
    engine = create_engine(TEST_DB_URL)

    try:
        import app.users.models  # noqa: F401
        import app.auth.models  # noqa: F401
        import app.links.models  # noqa: F401
        import app.analytics.models  # noqa: F401
        from app.users.models import User
        from app.auth.service import create_user_session
        from sqlalchemy.orm import sessionmaker

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        user = db.query(User).filter_by(email="httpx_click_test@example.com").first()
        if not user:
            user = User(email="httpx_click_test@example.com", name="Httpx Click User")
            db.add(user)
            db.commit()
            db.refresh(user)
        raw_token, _ = create_user_session(db, user.id)
        db.close()

        base_url = f"http://127.0.0.1:{SERVER_PORT}"
        limits = httpx.Limits(max_keepalive_connections=100, max_connections=100)
        async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=10.0) as client:
            code_suffix = int(time.time()) % 100000
            custom_code = f"rc_{code_suffix}"

            # Create test link
            create_resp = await client.post(
                "/api/links",
                json={"original_url": "https://example.com/dest_target", "custom_code": custom_code},
                headers={"Cookie": f"session_token={raw_token}", "Origin": "http://localhost:5173"},
            )
            assert create_resp.status_code == 201, f"Create failed: {create_resp.status_code} {create_resp.text}"
            link_id = create_resp.json()["id"]
            print(f"Created link id={link_id}, short_code={custom_code}")

            # -------------------------------------------------------------
            # ITEM 1: 200 sequential + 500 concurrent (50 concurrency)
            # -------------------------------------------------------------
            print("\n[Item 1 Verification] Sending 200 sequential GET redirects...")
            seq_latencies = []
            seq_302s = 0
            for _ in range(200):
                t0 = time.perf_counter()
                r = await client.get(f"/{custom_code}", follow_redirects=False)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                seq_latencies.append(elapsed_ms)
                if r.status_code == 302:
                    seq_302s += 1

            print(f"  Sequential 302s: {seq_302s}/200 (p50: {calc_p(seq_latencies, 50):.2f}ms, p95: {calc_p(seq_latencies, 95):.2f}ms)")

            print("[Item 1 Verification] Sending 500 concurrent GET redirects (50 concurrency)...")
            conc_302s, conc_latencies = await run_concurrent_batch_with_latencies(client, f"/{custom_code}", 500, concurrency=50)
            print(f"  Concurrent 302s: {conc_302s}/500 (p50: {calc_p(conc_latencies, 50):.2f}ms, p95: {calc_p(conc_latencies, 95):.2f}ms)")

            total_item1_302s = seq_302s + conc_302s
            item1_all_latencies = seq_latencies + conc_latencies

            print("Waiting 5 seconds for background tasks...")
            await asyncio.sleep(5)

            with engine.connect() as conn:
                item1_clicks = conn.execute(
                    text("SELECT count(*) FROM click_events WHERE link_id = :lid"),
                    {"lid": link_id},
                ).scalar()

            print(f"  Item 1 Total 302s: {total_item1_302s}")
            print(f"  Item 1 DB Clicks:  {item1_clicks}")
            print(f"  Item 1 Equal:      {total_item1_302s == item1_clicks}")
            print(f"  Item 1 Latency:    p50 = {calc_p(item1_all_latencies, 50):.2f} ms, p95 = {calc_p(item1_all_latencies, 95):.2f} ms")

            # -------------------------------------------------------------
            # ITEM 4: Redirect load test with 50 concurrent clients (1,000 requests)
            # -------------------------------------------------------------
            load_code = f"ld_{code_suffix}"
            create_load = await client.post(
                "/api/links",
                json={"original_url": "https://example.com/dest_load", "custom_code": load_code},
                headers={"Cookie": f"session_token={raw_token}", "Origin": "http://localhost:5173"},
            )
            assert create_load.status_code == 201, f"Create load link failed: {create_load.status_code}"
            load_link_id = create_load.json()["id"]

            print(f"\n[Item 4 Verification] Running 1,000 redirect requests with 50 concurrent clients on /{load_code}...")
            t_start = time.perf_counter()
            load_302s, load_latencies = await run_concurrent_batch_with_latencies(client, f"/{load_code}", 1000, concurrency=50)
            total_duration = time.perf_counter() - t_start
            throughput = len(load_latencies) / total_duration

            print(f"  Completed in {total_duration:.2f}s ({throughput:.1f} req/s)")
            print("Waiting 5 seconds for background tasks...")
            await asyncio.sleep(5)

            with engine.connect() as conn:
                load_clicks = conn.execute(
                    text("SELECT count(*) FROM click_events WHERE link_id = :lid"),
                    {"lid": load_link_id},
                ).scalar()

            p50_load = calc_p(load_latencies, 50)
            p95_load = calc_p(load_latencies, 95)
            p99_load = calc_p(load_latencies, 99)

            print(f"  Item 4 302 Responses: {load_302s}/1000")
            print(f"  Item 4 DB Clicks:     {load_clicks}")
            print(f"  Item 4 Equal:         {load_302s == load_clicks}")
            print(f"  Item 4 Latency:       p50 = {p50_load:.2f} ms, p95 = {p95_load:.2f} ms, p99 = {p99_load:.2f} ms")

    finally:
        srv_proc.terminate()
        srv_proc.wait()
        print("\nChecking server log for errors...")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                logs = f.read()
                errors = [line for line in logs.splitlines() if "ERROR" in line or "Traceback" in line or "Failed to record" in line]
                if errors:
                    print(f"Found {len(errors)} error lines in server log:")
                    for e in errors[:10]:
                        print("  ", e)
                else:
                    print("Zero background-task or server errors found in log!")


if __name__ == "__main__":
    asyncio.run(main_async())

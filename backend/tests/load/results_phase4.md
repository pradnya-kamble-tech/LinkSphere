# Phase 4 Performance, Click Audit & Verification Report

## 1. Real-Server Click Verification & Redirect Load (asyncio + httpx)

Tested against real `uvicorn app.main:app` server (no `--reload`, single worker) and PostgreSQL test database (`linksphere_test`).

### Item 1: Click Equality Check (200 Sequential + 500 Concurrent at 50 Concurrency)
- **Sequential 302s Received**: 200 / 200 (p50: 10.40 ms, p95: 17.94 ms)
- **Concurrent 302s Received**: 500 / 500 (p50: 442.22 ms, p95: 1849.22 ms)
- **Total 302 Redirect Responses**: 700
- **Click Events Recorded in PostgreSQL**: 700
- **Discrepancy**: 0
- **Exact Match**: **PASS**
- **Overall Latency**: p50 = 263.08 ms, p95 = 1679.70 ms
- **Server Background-Task Errors in Log**: 0

### Item 4: Redirect Load (1,000 Requests at 50 Concurrency)
- **Total 302 Responses Received**: 1,000 / 1,000
- **Click Events Recorded in PostgreSQL**: 1,000
- **Discrepancy**: 0
- **Exact Match**: **PASS**
- **Throughput**: 73.2 req/s (1,000 requests in 13.66s)
- **Latencies**:
  - p50: **432.94 ms**
  - p95: **2078.45 ms**
  - p99: **3530.22 ms**
- **Server Background-Task Errors in Log**: 0

---

## 2. Database Round-Trip & `pool_pre_ping` Benchmark (Item 2)

Standalone script (`test_db_latency.py`), single psycopg connection, 500 sequential `SELECT 1` queries:
- **`localhost:5434`**: **0.554 ms** per round-trip
- **`127.0.0.1:5434`**: **1.411 ms** per round-trip
- **Impact of `pool_pre_ping`** on `/api/diagnostic/db-ping` at 50 concurrent users (15s):
  - With `pool_pre_ping=True`: 171.8 req/s, median 250 ms, p95 310 ms
  - With `pool_pre_ping=False`: 171.1 req/s, median 240 ms, p95 350 ms

---

## 3. `POST /api/links` Optimization & Verification (Item 3)

- **SQL Statement Count**: Exactly **6 statements** per request:
  1. Session token lookup (`SELECT sessions ...`)
  2. User lookup (`SELECT users ...`)
  3. `SAVEPOINT` creation
  4. `INSERT INTO links ... RETURNING links.id`
  5. `RELEASE SAVEPOINT`
  6. `SELECT links ...` (`db.refresh`)
- **DNS / Network Lookups**: **0**. Verified via unit test asserting no calls to `socket.getaddrinfo`, `socket.gethostbyname`, or `socket.gethostbyname_ex`.
- **Pre-check Query Elimination**: Removed pre-query `SELECT id FROM links WHERE short_code = ...` for both custom and generated codes, relying entirely on the PostgreSQL unique index + savepoint retry on collision.

---

## 4. Corrections & Withdrawn Claims (Item 5)

1. **Withdrawn "Virtually Zero Overhead" & "0.68x" claims**:
   - The previously claimed 0.68x ratio was an artifact of a truncated Locust run that exited after only 20 requests. Under true sustained load (Item 4), redirect p95 is ~2078 ms at 50 concurrency.
2. **Withdrawn "Docker/Windows 760ms" claim**:
   - The raw DB round-trip is 0.554 ms, disproving the claim that Docker socket translation takes 760 ms. The elevated p95 under load is caused by connection checkout queuing and ASGI event loop contention under 50 concurrent clients on a single worker.
3. **Corrected Click Audit Discrepancy**:
   - The earlier Locust discrepancy (0 clicks) occurred because a previous test step truncated the table and the test runner did not ensure the link existed prior to Locust firing. Real-server verification with `asyncio + httpx` proves 100% click recording accuracy (700/700 and 1000/1000) with 0 errors.

---

## 5. HTML Error Pages & XSS Safety (Item 6)

- HTML pages for 404 (`HTML_404`) and 410 (`HTML_410`) are static constants that never reflect the input `short_code` or any URL parameter.
- Verified with adversarial XSS payloads (`<script>alert(1)`, `<img src=x onerror=alert('xss')>`, `"><svg onload=alert(1)>`), confirming 0 unescaped reflection.

# Known Issues & Performance Regression Baseline

## 1. Documented Known Issues

### Issue 1: Unexplained ~100ms `/api/me` Latency at 50 Users
* **Observation**: Under 50 concurrent users, `GET /api/me` (session validation + user lookup) records a p95 response time of ~120 ms (median 110 ms).
* **Investigation & Contrast**:
  * Pure database query execution time measured via `EXPLAIN (ANALYZE, BUFFERS)` is under **0.25 ms** (index scan on `token_hash` takes 0.100 ms; primary key lookup on `users` takes 0.019 ms).
  * Framework baseline (`ping-async`) without database work yields p95 of **8 ms** at 50 users.
* **Open Hypothesis**: Latency overhead stems from database round-trip transit over Docker-to-Windows host networking, connection checkout contention from SQLAlchemy's connection pool, or threadpool handoff in ASGI workers.
* **Next Action**: Phase 4 begins with a single no-auth baseline endpoint running `SELECT 1` through the connection pool at 50 users to isolate host/Docker network latency from application code.

### Issue 2: Unexplained ~9s Callback p95 Latency at 50 Users
* **Observation**: `GET /api/auth/callback/google` records a p95 latency of ~9.2–9.3 seconds under 50 concurrent users.
* **Investigation & Contrast**:
  * Token exchange against the mock provider completes in < 2 ms in isolation.
  * In-memory RSA signature verification takes < 1 ms.
* **Open Hypothesis**: Under sustained concurrency, concurrent callback requests experience queuing delays in the threadpool during the combined user/identity find-or-create savepoint transaction or client connection throttling.
* **Status**: Logged as a known issue; optimization deferred.

### Issue 3: Large Account Analytics Scaling & Daily Rollup Architecture
* **Observation**: In a multi-tenant dataset (1,000,000 total click_events), querying analytics across 1,000 links for a single power user (~100,000 clicks) takes ~55–165 ms via Parallel Seq Scan. Single-link queries execute in sub-millisecond time (< 0.2 ms) via index-only scans on `(link_id, clicked_at)`, and typical users (20 links) execute in ~30 ms via nested loop index scans. Adding an index on `(clicked_at)` does not improve this plan because a 30-day window touches >20% of the table.
* **Architecture Decision**: No new index added to `click_events` to preserve fast 302 redirect write throughput. If an individual account reaches millions of clicks, introduce a daily rollup table (e.g. `daily_link_metrics` with `(link_id, date, click_count)` updated via periodic background aggregation or continuous materialized view).

### Issue 4: Analytics Rate Limiting (60 requests/minute per user)
* **Requirement**: Analytics endpoints (`/api/analytics/summary`, `/timeseries`, `/top-links`, `/breakdown`) should enforce a rate limit of 60 requests/minute per user.
* **Architecture Decision**: Recorded as an architectural requirement for Phase 7 / gateway deployment: rate limiting at 60 req/min per user prevents database threadpool and CPU saturation on heavy multi-link aggregation queries.

### Issue 5: Multi-Worker vs Single-Worker Throughput Discrepancy
* **Observation**: Running across 4 distributed uvicorn workers did not improve throughput or latency over a single worker:
  * Redirect endpoint: 1 worker achieved **76.5 req/s** (p95 1,817 ms), whereas 4 workers achieved **63.8 req/s** (p95 1,825 ms).
  * Breakdown endpoint: 1 worker achieved **8.0 req/s** (p95 11.4 s), whereas 4 workers achieved **5.9 req/s** (p95 12.6 s).
* **Cause**: **UNKNOWN**.
* **Deployment Context Note**: All load numbers originate from a single Windows laptop concurrently executing the load generator client, FastAPI/uvicorn server(s), and Docker Engine running PostgreSQL 16. These measurements reflect local resource contention and are **not a capacity statement**; all benchmarks must be re-measured on the production deployment host.

### Issue 6: Typical-User Under-Load Tail Latency
* **Observation**: Under 50 concurrent users, `GET /api/analytics/summary` for a typical user (20 links, 2,000 clicks) recorded a p95 latency of ~4.5–7.1 s on a 1M-row dataset.
* **Investigation**: Pure query execution time is 19.9–30.8 ms. The p95 measured right after seeding 1M rows remained > 1 s even after manual `ANALYZE` and waiting for PostgreSQL autovacuum/analyze workers to be completely idle (p50: 1,336 ms, p95: 4,540 ms). Root cause unknown; consistent with queueing but not proven. Re-measure on the deployment host with a scaling curve at 1, 5, 20 and 50 concurrent users to see whether the server saturates or serializes. This is **not a capacity statement**.

### Issue 7: CASE Bucketing vs AT TIME ZONE Tradeoff
* **Observation**: In the 1,000,000-row dataset:
  * For a typical 20-link user, Python-computed binary search CASE bucketing is **22.8% faster** than `AT TIME ZONE` (30.8 ms vs 39.9 ms).
  * For a 1,000-link user across a 30-day window, CASE bucketing is **131.7% slower** than `AT TIME ZONE` (304.3 ms vs 131.3 ms).
* **Architecture Decision**: Python-computed CASE bucketing is intentionally retained in the codebase for safety and simplicity: it ensures Postgres never parses user-supplied timezone names (preventing 500 errors and SQL injection), while keeping typical account performance fast. High-volume enterprise accounts will be handled by the daily rollup table.

### Issue 8: Breakdown Query Optimization vs Concurrency Behavior
* **Observation**: Unifying the two breakdown aggregations (referrers and device types) into a single SQL pass using `GROUP BY GROUPING SETS ((host_ref), (dev_type))` successfully halved the standalone database execution time from **121.7 ms to 61.4 ms**.
* **Load Test Behavior**: However, under 50 concurrent users on the heavy user, observed throughput shifted from 13.3 req/s (p95 4,498 ms) to 8.0 req/s (p95 11,444 ms). Thus, the only measured improvement from `GROUPING SETS` is in standalone query execution time, not under sustained single-host concurrent load. This is **not a capacity statement**.

### Issue 9: Account Deletion Architecture Decision (Option A)
* **Decided Design**: When account deletion is implemented in a future level, it must follow Option A: anonymize the user record (`name = "Deleted User"`, `email = "deleted_<uuid>@anonymized.local"`, `avatar_url = None`), revoke all sessions and OAuth identities, and keep links as soft-deleted (`deleted_at = now()`, `is_active = False`) so that short codes stay reserved forever.
* **Database Constraint Migration Note**: A future migration should switch `links.user_id` foreign key constraint to `ON DELETE RESTRICT` (instead of `CASCADE`) and update `test_user_delete_cascade` accordingly to prevent accidental hard deletion of links and release of reserved codes.

### Issue 10: Settings Endpoints Rate Limiting (30 requests/minute per user)
* **Requirement**: Level 7 settings and session management endpoints (`/api/me/identities`, `/api/me/sessions`, `/api/auth/logout-all`, `DELETE /api/me/sessions/{id}`) should enforce a rate limit of 30 requests/minute per user at the API gateway / proxy layer.
* **Architecture Decision**: Recorded as an architectural requirement for Level 4.5 gateway configuration to prevent abuse of session listing and mass revocation endpoints.

---

## 2. Phase 3 Performance Regression Baseline

These measured numbers serve as the official regression baseline for all subsequent phases.

### 50 Concurrent Users Baseline

| Endpoint / Scenario | Original Target (Reported) | Phase 3 Baseline p95 (1 Worker) | Phase 3 Baseline p95 (4 Workers) | Max Allowed (+25% Gate, 4W) |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/me [Valid Session]` | p95 < 50 ms | 120 ms | 120 ms | **150 ms** |
| `POST /api/auth/logout` | p95 < 50 ms | 130 ms | 79 ms | **98.8 ms** |
| `GET /api/me [Invalid/Forged 401]` | p95 < 30 ms | 130 ms | 40 ms | **50 ms** |
| `GET /api/auth/callback/google [New User]` | p95 < 100 ms | 9,300 ms | 9,200 ms | **11,500 ms** |
| `GET /api/auth/callback/google [Returning User]` | p95 < 100 ms | 9,300 ms | 9,200 ms | **11,500 ms** |

### 200 Concurrent Users Baseline

| Endpoint / Scenario | Original Target (Reported) | Phase 3 Baseline p95 (1 Worker) | Phase 3 Baseline p95 (4 Workers) | Max Allowed (+25% Gate, 4W) |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/me [Valid Session]` | p95 < 50 ms | 8,100 ms | 470 ms | **587.5 ms** |
| `POST /api/auth/logout` | p95 < 50 ms | 8,000 ms | 480 ms | **600 ms** |
| `GET /api/me [Invalid/Forged 401]` | p95 < 30 ms | 8,000 ms | 380 ms | **475 ms** |
| `GET /api/auth/callback/google [New User]` | p95 < 100 ms | 2,300 ms | 2,400 ms | **3,000 ms** |
| `GET /api/auth/callback/google [Returning User]` | p95 < 100 ms | 2,500 ms | 2,400 ms | **3,000 ms** |

---

## 3. Performance Gate for Later Phases

Replaces the earlier strict threshold gates as the pass condition for future phases:
1. **Zero Errors**: Exactly 0.0% failure rate under load.
2. **Regression Cap**: No endpoint may be more than **25% slower** than the Phase 3 baseline p95 for that endpoint at the corresponding concurrency level.
3. **Target Tracking**: The original targets (e.g., p95 < 50 ms) remain documented as target aspirations and are reported honestly, but are non-blocking.

---

## 4. Standing Rule F (Load Test Timebox)

* If load-test tooling or the test harness fails twice in a phase:
  * Stop immediately.
  * Report what failed.
  * Continue with the rest of the phase.
* Load tests are executed **once per phase**, strictly against only the endpoints that the phase adds or changes, utilizing the existing scripts.
* Never spend more than ~20 minutes of effort on load-test tooling problems without explicit operator approval.

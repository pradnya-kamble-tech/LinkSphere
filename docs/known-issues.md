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

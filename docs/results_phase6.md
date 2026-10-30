# Phase 6 Load Benchmark Results

All benchmarks below were recorded on a single Windows development machine running the load generator, FastAPI application, and Docker PostgreSQL 16 database. These results reflect local system contention and are **not a capacity statement**; all figures must be re-measured on the production deployment host.

---

## 1. Analytics Endpoints Baseline (50 Concurrent Users, 15s per run)

Multi-tenant dataset size: **1,000,000 total click_events**.
Heavy User: 20 links, 100,000 clicks.
Typical User: 20 links, 2,000 clicks.

| User Type | Endpoint | Workers | Completed Requests | Throughput (req/s) | p50 Latency (ms) | p95 Latency (ms) | Status Codes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Typical User** | `GET /api/analytics/summary` | 1 | 338 | 25.5 | 1,336.04 | 4,540.22 | `{200: 338}` |
| **Typical User** | `GET /api/analytics/breakdown` | 1 | 413 | 27.0 | 344.18 | 7,277.58 | `{200: 413}` |
| **Heavy User** | `GET /api/analytics/summary` | 1 | 1,035 | 66.0 | 524.16 | 1,931.72 | `{200: 1035}` |
| **Heavy User** | `GET /api/analytics/timeseries` | 1 | 764 | 44.5 | 658.12 | 3,101.32 | `{200: 764}` |
| **Heavy User** | `GET /api/analytics/top-links` | 1 | 572 | 36.8 | 871.77 | 4,003.86 | `{200: 572}` |
| **Heavy User (Initial 2 Queries)** | `GET /api/analytics/breakdown` | 1 | 244 | 13.3 | 3,563.99 | 4,498.56 | `{200: 244}` |
| **Heavy User (GROUPING SETS)** | `GET /api/analytics/breakdown` | 1 | 127 | 8.0 | 1,375.64 | 11,443.97 | `{200: 127}` |
| **Heavy User** | `GET /api/analytics/summary` | 4 | 301 | 19.8 | 340.82 | 9,622.77 | `{200: 301}` |
| **Heavy User** | `GET /api/analytics/breakdown` | 4 | 93 | 5.9 | 2,166.22 | 12,559.15 | `{200: 93}` |

---

## 2. Key Observations & Architecture Notes

1. **Breakdown Query Optimization**:
   * The only measured improvement from `GROUPING SETS` is standalone database execution time (halved from ~122 ms to ~61 ms). Under concurrent load, throughput shifted from 13.3 to 8.0 req/s and p95 rose from 4.5 s to 11.4 s due to lock/threadpool contention. No load improvement is claimed.
2. **Worker Scaling Discrepancy**:
   * Across both redirect and analytics endpoints, 4 workers did not yield higher throughput than 1 worker (Redirect: 63.8 vs 76.5 req/s; Breakdown: 5.9 vs 8.0 req/s). Cause is UNKNOWN in local Windows Docker environment.
3. **Typical-User Under-Load Latency**:
   * Measured p95 of ~4.5–7.2 s for typical users under 50 simultaneous connections remained > 1 s even after manual `ANALYZE` and confirming idle PostgreSQL autovacuum processes. Root cause unknown; consistent with queueing but not proven. Re-measure on the deployment host with a scaling curve at 1, 5, 20 and 50 concurrent users to see whether the server saturates or serializes. This is not a capacity statement.
4. **Timezone Bucketing Choice**:
   * Python-computed CASE bucketing is 22.8% faster than `AT TIME ZONE` for typical users (30.8 vs 39.9 ms), but 131.7% slower for 1,000-link users (304.3 vs 131.3 ms). CASE bucketing is retained for safety against invalid IANA timezone 500s.

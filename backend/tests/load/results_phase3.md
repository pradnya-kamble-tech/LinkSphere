# Phase 3 Load Test & Diagnostics Results

> **Environment**: Local Windows Laptop (Intel/AMD multi-core, PostgreSQL on Docker host port 5434).

## 1. Approved Thresholds vs Actual Results

| Endpoint / Scenario | Concurrency | Approved Threshold | Actual p95 (1 Worker) | Actual p95 (4 Workers) | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /api/me [Valid Session]` | 50 users | p95 < 50ms | 120 ms | 120 ms | **FAIL** |
| `POST /api/auth/logout` | 50 users | p95 < 50ms | 130 ms | 79 ms | **FAIL** |
| `GET /api/me [Invalid/Forged 401]` | 50 users | p95 < 30ms | 130 ms | 40 ms | **FAIL** |
| `GET /api/auth/callback/google [New User]` | 50 users | p95 < 100ms | 9300 ms | 9200 ms | **FAIL** |
| `GET /api/auth/callback/google [Returning User]` | 50 users | p95 < 100ms | 9300 ms | 9200 ms | **FAIL** |
| `GET /api/me [Valid Session]` | 200 users | p95 < 50ms | 8100 ms | 470 ms | **FAIL** |
| `POST /api/auth/logout` | 200 users | p95 < 50ms | 8000 ms | 480 ms | **FAIL** |
| `GET /api/me [Invalid/Forged 401]` | 200 users | p95 < 30ms | 8000 ms | 380 ms | **FAIL** |
| `GET /api/auth/callback/google [New User]` | 200 users | p95 < 100ms | 2300 ms | 2400 ms | **FAIL** |
| `GET /api/auth/callback/google [Returning User]` | 200 users | p95 < 100ms | 2500 ms | 2400 ms | **FAIL** |

## 2. Framework vs Database Diagnosis (Trivial Baselines)

| Scenario | Users | Req/s | Median (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| GET /api/diagnostic/ping-async [No-DB Async] | async_50 | 1375.9 | 3 | 8 | 11 |
| GET /api/diagnostic/ping-sync [No-DB Sync] | sync_50 | 1230.1 | 7 | 18 | 47 |
| GET /api/diagnostic/ping-async [No-DB Async] | async_200 | 2536.2 | 16 | 37 | 59 |
| GET /api/diagnostic/ping-sync [No-DB Sync] | sync_200 | 2011.6 | 36 | 98 | 120 |

## 3. Worker Concurrency: 1 Worker vs 4 Workers

### 50 Concurrent Users

| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/auth/callback/google [New User]` | 1.51 | 9300 ms | 1.49 | 9200 ms |
| `GET /api/auth/callback/google [Returning User]` | 1.51 | 9300 ms | 1.49 | 9200 ms |
| `GET /api/me [Invalid/Forged 401]` | 43.03 | 130 ms | 90.55 | 40 ms |
| `GET /api/me [Valid Session]` | 70.72 | 120 ms | 82.43 | 120 ms |
| `POST /api/auth/logout` | 19.58 | 130 ms | 27.48 | 79 ms |
| `Aggregated` | 136.35 | 480 ms | 203.45 | 110 ms |

### 200 Concurrent Users

| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/auth/callback/google [New User]` | 3.08 | 2300 ms | 3.18 | 2400 ms |
| `GET /api/auth/callback/google [Returning User]` | 3.08 | 2500 ms | 3.11 | 2400 ms |
| `GET /api/me [Invalid/Forged 401]` | 43.47 | 8000 ms | 78.52 | 380 ms |
| `GET /api/me [Valid Session]` | 68.39 | 8100 ms | 122.66 | 470 ms |
| `POST /api/auth/logout` | 24.06 | 8000 ms | 39.97 | 480 ms |
| `Aggregated` | 142.09 | 8000 ms | 247.43 | 2200 ms |

## 4. CPU Utilization Profiling

| Run Scenario | Server Workers | System CPU % |
| :--- | :--- | :--- |
| 50 Users Core Auth | 1 Worker | 23.3% |
| 200 Users Core Auth | 1 Worker | 22.5% |
| 50 Users Core Auth | 4 Workers | 33.4% |
| 200 Users Core Auth | 4 Workers | 45.3% |

*(Note: Locust client process CPU monitoring has been removed as the initial 0.0% reading was an inaccurate/broken subprocess measurement on Windows).*

## 5. last_seen_at Throttling (Design Rationale, Not Measured)

The decision to throttle updates to `sessions.last_seen_at` (updating only if the recorded timestamp is older than 5 minutes) is a **design rationale, not measured**.

**Rationale**: Unconditional updates on every authenticated request turn read-only queries (`GET /api/me`) into database `UPDATE` transactions. In PostgreSQL, this causes write-ahead log (WAL) flushes and row-level locking on the `sessions` row. Throttling ensures that high-frequency reads remain non-blocking `SELECT` queries across concurrent requests.

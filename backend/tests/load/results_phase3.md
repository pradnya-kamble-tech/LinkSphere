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
| GET /api/diagnostic/ping-async [No-DB Async] | async_50 | 1375.936207941134 | 3 | 8 | 11 |
| GET /api/diagnostic/ping-sync [No-DB Sync] | sync_50 | 1230.1412654135827 | 7 | 18 | 47 |
| GET /api/diagnostic/ping-async [No-DB Async] | async_200 | 2536.2123023401737 | 16 | 37 | 59 |
| GET /api/diagnostic/ping-sync [No-DB Sync] | sync_200 | 2011.6027485439888 | 36 | 98 | 120 |

## 3. Worker Concurrency: 1 Worker vs 4 Workers

### 50 Concurrent Users

| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/auth/callback/google [New User]` | 1.5062247441686374 | 9300 ms | 1.4949110872071962 | 9200 ms |
| `GET /api/auth/callback/google [Returning User]` | 1.5062247441686374 | 9300 ms | 1.4949110872071962 | 9200 ms |
| `GET /api/me [Invalid/Forged 401]` | 43.0349926905325 | 130 ms | 90.54890013940732 | 40 ms |
| `GET /api/me [Valid Session]` | 70.7208379881084 | 120 ms | 82.43366852313969 | 120 ms |
| `POST /api/auth/logout` | 19.580921674192286 | 130 ms | 27.47788950771323 | 79 ms |
| `Aggregated` | 136.34920184117047 | 480 ms | 203.4502803446746 | 110 ms |

### 200 Concurrent Users

| Endpoint | 1-Worker Req/s | 1-Worker p95 | 4-Worker Req/s | 4-Worker p95 |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/auth/callback/google [New User]` | 3.0794837567818876 | 2300 ms | 3.1776070782115675 | 2400 ms |
| `GET /api/auth/callback/google [Returning User]` | 3.0794837567818876 | 2500 ms | 3.106993587584644 | 2400 ms |
| `GET /api/me [Invalid/Forged 401]` | 43.47085210154897 | 8000 ms | 78.52220157713919 | 380 ms |
| `GET /api/me [Valid Session]` | 68.39318576108612 | 8100 ms | 122.65563321896651 | 470 ms |
| `POST /api/auth/logout` | 24.06294284369103 | 8000 ms | 39.96723569483883 | 480 ms |
| `Aggregated` | 142.0859482198899 | 8000 ms | 247.42967115674074 | 2200 ms |

## 4. CPU Utilization Profiling

| Run Scenario | Server Workers | Locust CPU % | System CPU % |
| :--- | :--- | :--- | :--- |
| 50 Users Core Auth | 1 Worker | 0.0% | 23.3% |
| 200 Users Core Auth | 1 Worker | 0.0% | 22.5% |
| 50 Users Core Auth | 4 Workers | 0.0% | 33.4% |
| 200 Users Core Auth | 4 Workers | 0.0% | 45.3% |

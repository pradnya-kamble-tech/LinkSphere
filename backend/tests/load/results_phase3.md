# Phase 3 Load Test Results

> **Note**: Local machine baseline numbers, not production capacity.

## Users 50

| Endpoint / Task | Requests | Failures | Req/s | p50 (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| GET /api/me [Invalid/Forged 401] | 914 | 0 | 65.03095728569008 | 180 | 340 | 410 |
| GET /api/me [Valid Session] | 1525 | 0 | 108.50351188257918 | 170 | 350 | 460 |
| POST /api/auth/logout | 526 | 0 | 37.42481786900763 | 170 | 350 | 420 |
| Aggregated | 2965 | 0 | 210.95928703727688 | 170 | 340 | 430 |

## Users 200

| Endpoint / Task | Requests | Failures | Req/s | p50 (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| GET /api/me [Invalid/Forged 401] | 888 | 0 | 63.05269866404272 | 860 | 1300 | 1300 |
| GET /api/me [Valid Session] | 1112 | 0 | 78.95788391263007 | 1200 | 1600 | 2300 |
| POST /api/auth/logout | 451 | 0 | 32.02338637103971 | 1200 | 1500 | 1600 |
| Aggregated | 2451 | 0 | 174.0339689477125 | 1000 | 1500 | 1900 |


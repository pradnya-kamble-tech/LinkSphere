# Phase 4 Load Test & Performance Baselines

> **Setup**: 50 Concurrent Users, 15s duration per test, single worker without `--reload`, target database `linksphere_test`.

## 1. Phase 4 Endpoints & Ratio Relative to `db-ping` (`SELECT 1`)

* **`db-ping` (`SELECT 1`) Baseline p95**: **760.0 ms** (Throughput: 131.30294300527066 req/s)

| Endpoint | Request Count | Failures | Req/s | Median (ms) | p95 (ms) | p99 (ms) | Ratio vs db-ping p95 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /api/diagnostic/db-ping [SELECT 1]` | 1482 | 0 | 131.30294300527066 | 260 | **760.0** | 1800 | **1.0x** |
| `GET /{short_code} [Redirect 302]` | 20 | 0 | 35.38757938742752 | 490 | **520.0** | 520 | **0.68x** |
| `POST /api/links [Create Link]` | 89 | 0 | 7.929154311605121 | 9500 | **11000.0** | 11000 | **14.47x** |
| `GET /api/links [1000 Links + 100k Clicks]` | 555 | 0 | 44.37010217724385 | 970 | **1700.0** | 2200 | **2.24x** |

## 2. Redirect Click Audit

- **302 Redirect Responses Delivered**: 20
- **Click Events Recorded in Database**: 0
- **Redirect Failures / Dropped Requests**: 0
- **Exact Match (302 Count == Click Count & 0 Errors)**: **FAIL**

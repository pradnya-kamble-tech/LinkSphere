# LinkSphere v2 Production Deployment Plan v4 (Vercel + Serverless Architecture)

> **Important**: This document is an architectural and operational plan only. No deployment code or application changes have been committed. All external platform limits, prices, and features are marked with **(verify)** and cited against official vendor documentation.

---

## 0. Operator Decisions & Target Configuration

The following parameters are established for this deployment target:

* **Target Domain**: None (Custom domain deferred). Utilizing default platform production subdomain: `https://<project>.vercel.app`.
* **Hosting Topology**: **Option V (Vercel + Hosted Postgres with Connection Pooler, proposing Neon)**. Fallback: **Option V2 (Hybrid Vercel Frontend + Container API via Vercel Rewrites)**.
* **Monthly Budget Ceiling**: **Free tiers only** (Vercel Hobby + Neon Free Tier, to be confirmed by operator).
* **Application Rate Limiter**: Hand-written application logic (zero external paid services or unapproved dependencies).

---

## 1. Hosting Options (Single-Origin Serverless Topologies)

### Option V: Vercel Unified (Static Frontend + Python ASGI Serverless Function + Neon)
In Option V, the entire application is hosted on Vercel under a single origin (`https://<project>.vercel.app`), connecting to Neon Serverless Postgres via its built-in connection pooler:

```
                                    [ Client Browser ]
                                            │
                                            ▼ HTTPS
                            ┌───────────────────────────────┐
                            │    https://<project>.vercel.app│
                            └───────────────┬───────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
         [ Vercel CDN / Static Edge ]             [ Vercel Serverless Function ]
         (Vite React SPA: /assets/*,               (Python 3.11+ ASGI: /api/*,
          /login, /dashboard, etc.)                 /{short_code} redirects)
                                                                   │
                                                                   ▼ SQL (Port 5432, Pooler)
                                                   ┌───────────────────────────────┐
                                                   │ Neon PostgreSQL 16 (Pooled)   │
                                                   │ Built-in PgBouncer (Tx Mode)  │
                                                   └───────────────────────────────┘
```

- **Pros**:
  - Zero infrastructure management, zero VM patching.
  - Generous free tiers on both Vercel and Neon.
  - Automatic HTTPS, global CDN edge for static assets, and built-in Git deployment pipelines.
  - Single origin eliminates CORS preflight overhead and cross-origin cookie restrictions.
- **Cons**:
  - Python cold starts on initial invocations (800ms–2.5s) **(verify)**.
  - 10-second maximum request execution timeout on Vercel Hobby tier **(verify)**.
  - Ephemeral function instances prevent in-memory state sharing (rate limiting requires database backing).
  - Background tasks freeze upon response return (click events must be committed synchronously before redirecting).
- **Cost**: **$0/month** on Hobby/Free tiers **(verify)**.

---

### Fallback Option V2: Hybrid Single-Origin (Vercel Frontend + Container API via Rewrites)
If Vercel's Python serverless execution, cold starts, or background execution limits prove untenable during Spike 0, Option V2 retains a single origin by proxying API calls through Vercel's Edge network:

```
                                    [ Client Browser ]
                                            │
                                            ▼ HTTPS
                            ┌───────────────────────────────┐
                            │    https://<project>.vercel.app│
                            └───────────────┬───────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
         [ Vercel CDN / Static Edge ]                   [ Vercel Edge Rewrites ]
         (Vite React SPA: /assets/*,                   /api/* and /{short_code}
          /login, /dashboard, etc.)                                │
                                                                   ▼ HTTPS
                                                       ┌───────────────────────────────┐
                                                       │ Standalone Container API      │
                                                       │ (Render / Railway / VPS)      │
                                                       └───────────────┬───────────────┘
                                                                       │
                                                                       ▼ SQL
                                                       ┌───────────────────────────────┐
                                                       │ Managed PostgreSQL 16         │
                                                       └───────────────────────────────┘
```

- **How it preserves Single Origin**: `vercel.json` rewrites `/api/:path*` and `/:short_code` to the backend container URL (`https://api-backend.onrender.com`). To the browser, all cookies and network requests remain bound strictly to `https://<project>.vercel.app`.
- **Pros**: Long-running workers, persistent threadpool, reliable background tasks, zero serverless cold starts.
- **Cons**: Requires managing a second hosting provider; potential double-hop network latency on API calls.

---

## 2. Serverless Feasibility Checklist (Official Documentation Audit)

Audit evaluated against official [Vercel Documentation](https://vercel.com/docs) and [Neon Documentation](https://neon.tech/docs):

| Feature / Requirement | Status | Official Limit / Specification | Source / Documentation Reference |
| :--- | :---: | :--- | :--- |
| **Python & FastAPI Support** | **OK** | Native support via `@vercel/python` builder or `/api/index.py` ASGI handler. Python 3.9–3.12 supported. | Vercel Docs: Serverless Functions (Python Runtime) |
| **Function Bundle Size** | **OK** | **50 MB** compressed, **250 MB** uncompressed. LinkSphere backend dependencies (FastAPI, SQLAlchemy, Authlib, Pydantic) consume ~45 MB uncompressed. | Vercel Docs: Serverless Functions Limitations **(verify)** |
| **Execution Duration Limit** | **OK (verify)**| **10 seconds** default & maximum on Hobby Free tier; up to 300s on Pro. Redirects and API endpoints execute in < 200 ms. | Vercel Docs: Functions Execution Limits **(verify)** |
| **Function Memory Limit** | **OK (verify)**| **1024 MB** default on Hobby tier. More than sufficient for LinkSphere's ~120 MB runtime RSS. | Vercel Docs: Functions Memory Limits **(verify)** |
| **Cold-Start Behavior** | **(verify)** | Python runtime initialization + importing SQLAlchemy/Pydantic models takes **800 ms to 2.5 s** on cold invocations. | Community benchmarks & Vercel Runtime metrics **(verify)** |
| **Post-Response Work (BackgroundTasks)**| **NOT OK** | Once HTTP response finishes transmitting, AWS Lambda/Vercel execution context freezes immediately. Uncommitted background tasks or async tasks will freeze or drop. | AWS Lambda Execution Lifecycle / Vercel Functions Docs |
| **Psycopg3 Binary Wheels** | **OK** | `psycopg[binary]` provides pre-compiled `manylinux` x86_64 wheels that run on Vercel's Amazon Linux runtime without requiring native compilation or `libpq-dev`. | PyPI / Psycopg documentation |
| **Hobby Plan Terms** | **OK** | Free for personal, non-commercial applications. Commercial usage requires Pro. | Vercel Fair Use Policy / Terms of Service |
| **Deployment Protection (OAuth Impact)**| **(verify)**| Preview deployments enable "Vercel Authentication" by default, blocking incoming webhooks and OAuth callbacks. Production deployments (`<project>.vercel.app`) are public by default. | Vercel Docs: Deployment Protection **(verify)** |
| **Platform Rate Limiting** | **(verify)**| Custom WAF rate-limiting rules are restricted to Vercel Pro with Firewall add-on. Hobby tier includes only automated DDoS/Attack Challenge Mode. | Vercel Docs: Security & WAF Rules **(verify)** |
| **Neon Connection Pooler** | **OK** | Built-in PgBouncer in transaction mode accessible via connection string host with `-pooler` suffix on port `5432`. | Neon Docs: Connection Pooling |
| **Neon Free Tier Compute Limits** | **(verify)**| 0.5 GiB storage, compute scales to zero after 5 minutes of inactivity. Cold activation takes ~500 ms–2 s. | Neon Docs: Free Tier & Autosuspend **(verify)** |

---

## 3. `vercel.json` Routing Design & Route Synchronization

### Route Precedence & Ordering
In Vercel, `routes` or `rewrites` in `vercel.json` are evaluated sequentially. The routing table must prioritize hashed static assets and frontend SPA pages before falling back to the serverless function for API and short-code redirects:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "frontend/package.json",
      "use": "@vercel/static-build",
      "config": { "distDir": "dist" }
    },
    {
      "src": "backend/api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/assets/(.*)",
      "headers": { "cache-control": "public, max-age=31536000, immutable" },
      "dest": "/assets/$1"
    },
    {
      "src": "/(favicon\\.ico|robots\\.txt|sitemap\\.xml)",
      "dest": "/$1"
    },
    {
      "src": "/api/(.*)",
      "dest": "backend/api/index.py"
    },
    {
      "src": "/(login|signup|dashboard|analytics|settings|)",
      "dest": "/index.html",
      "headers": { "cache-control": "no-cache, no-store, must-revalidate" }
    },
    {
      "src": "/([a-zA-Z0-9_-]{3,30})",
      "dest": "backend/api/index.py"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```

### Route Drift Synchronization
1. **Frontend Inventory**: From [`frontend/src/App.tsx`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/frontend/src/App.tsx), all active routes (`/`, `/login`, `/signup`, `/dashboard`, `/analytics`, `/settings`) are routed directly to `/index.html` by Vercel edge routers.
2. **`RESERVED_CODES` Integrity**: Any path routed to `index.html` or static assets **must** be listed in `RESERVED_CODES` in [`backend/app/links/schemas.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/links/schemas.py).
3. **Automated Drift Test**: CI pipeline executes `test_reserved_codes_cover_all_frontend_routes` ensuring any newly added route in `App.tsx` fails the build until registered in `RESERVED_CODES` and `vercel.json`.

### Preview vs Production URLs & OAuth Constraints
- **Vercel Preview URLs**: Every git push generates dynamic preview deployments (e.g. `https://linksphere-git-feat-x-user.vercel.app` or `https://linksphere-a1b2c3-user.vercel.app`).
- **OAuth Mismatch**: Third-party OAuth providers (Google, GitHub) strictly forbid wildcard callback URLs for security reasons. They require exact, literal redirect URIs.
- **Rule**: OAuth authentication is configured **strictly for the canonical production URL**:
  - `https://<project>.vercel.app/api/auth/callback/google`
  - `https://<project>.vercel.app/api/auth/callback/github`
- Preview branch testing must use mock auth or direct database-seeded sessions.

---

## 4. Serverless Database Architecture (Neon + Connection Pooling)

### Connection String Configuration
Neon provides two connection strings in its console:
1. **Pooled Connection String** (Used by FastAPI Serverless Function):
   ```
   postgresql+psycopg://user:password@ep-cold-name-pooler.region.aws.neon.tech/dbname?sslmode=require
   ```
2. **Direct Connection String** (Used for Alembic Migrations):
   ```
   postgresql+psycopg://user:password@ep-cold-name.region.aws.neon.tech/dbname?sslmode=require
   ```

### Serverless SQLAlchemy Pool Configuration
In serverless environments, each concurrent invocation or container replica runs an independent Python process. Standard connection pooling (`pool_size=10`) causes rapid connection multiplication under traffic spikes.
- **Recommended Strategy**: Use `NullPool` (or `pool_size=1, max_overflow=0`):
  ```python
  from sqlalchemy.pool import NullPool

  engine = create_engine(
      settings.DATABASE_URL,
      poolclass=NullPool,
      connect_args={"prepare_threshold": None},
  )
  ```
- **Why `prepare_threshold=None` is Mandatory**: Neon's connection pooler operates in **PgBouncer transaction mode**. Transaction pooling routes different queries within or across transactions to different PostgreSQL server connections. Psycopg 3's default prepared statement caching causes `SQLSTATE 26000: prepared statement does not exist` unless server-side statement preparation is disabled via `prepare_threshold=None`.

### Connection Budget Arithmetic
- Neon Free Tier PgBouncer limit: Supports **up to 10,000 pooled client connections** multiplexed onto a smaller backend connection pool **(verify)**.
- Direct connection limit: Capped at **100 concurrent connections** on Neon Free compute **(verify)**.
- With `NullPool` or `pool_size=1`, 50 concurrent Vercel function invocations open exactly 50 connections to Neon PgBouncer, easily within provider quotas.

### Database Migration Execution Strategy
- **Strict Rule**: Migrations (`alembic upgrade head`) must **NEVER** run inside the Vercel Serverless Function during startup. If multiple serverless instances cold-start concurrently, simultaneous DDL causes database migration deadlocks and function timeouts.
- **Execution Workflow**:
  1. Migrations are executed externally from a trusted local workstation or GitHub Actions CI step against Neon's **direct connection string**.
  2. The deployment pipeline requires operator confirmation before applying destructive schema changes.

---

## 5. Click Recording in Serverless (Durability vs Latency)

### Mechanism Comparison
In serverless execution environments, code behavior after sending the HTTP response differs fundamentally from traditional persistent containers:

| Approach | Description | Latency Impact | Durability Risk |
| :--- | :--- | :--- | :--- |
| **(a) Synchronous Insert Before Response** *(Default)* | Execute `INSERT INTO click_events` and update `click_count` within the database transaction, commit, then return `RedirectResponse(302)`. | Adds ~15–35 ms database round-trip to the redirect. | **Zero risk**. 100% durable; guaranteed click recording. |
| **(b) Post-Response Background Execution** | Return `RedirectResponse(302)` immediately and attempt to insert click event asynchronously via `BackgroundTasks`. | Zero added redirect latency. | **HIGH FAILURE RISK**. Once the response stream ends, Vercel/Lambda immediately freezes the CPU context. Background tasks freeze mid-execution and are either delayed indefinitely or terminated without committing. |

- **Architectural Decision**: **Default to (a) Synchronous Insert Before Response**. Mechanism (b) is rejected unless a platform-native post-response primitive (such as `@vercel/functions` `waitUntil`) is proven and officially supported for Python ASGI on Vercel.

### Staging Verification Test (Click Equality Gate)
Before approving production release, execute the click equality test:
- Automated test script issues $N = 100$ redirects (50 sequential, 50 concurrent) against `https://<project>.vercel.app/{short_code}`.
- Query database:
  ```sql
  SELECT count(*) FROM click_events WHERE link_id = :test_link_id;
  ```
- **Pass Criterion**: Exactly $N = 100$ rows recorded. If count $< 100$, the release is blocked.

---

## 6. Rate Limiting Architecture in Serverless

### The Serverless State Challenge
In-memory counters (`threading.Lock` + `collections.deque`) are stored in the memory space of a single serverless instance. Because Vercel dynamically spawns, scales, and destroys function containers across different edge nodes, in-process memory is not shared. An attacker or crawler hitting different serverless instances would experience reset limits.

### Evaluated Rate Limiting Options

| Option | Architecture | Pros | Cons / Dependencies |
| :--- | :--- | :--- | :--- |
| **Option 1: Database-Backed Atomic Counter** *(Proposed Default)* | Fixed-window table in PostgreSQL (`rate_limit_buckets`) updated via atomic `INSERT ... ON CONFLICT DO UPDATE`. | Zero new third-party accounts or dependencies. Shares state across all Vercel instances. | Adds a small database query overhead to rate-limited paths. |
| **Option 2: Upstash Serverless Redis** | External managed Redis accessed over HTTP REST API. | Sub-millisecond latency; purpose-built for serverless rate limiting. | Requires registering an Upstash account, managing keys, and adding `upstash-redis` dependency **(Ask before adding)**. |
| **Option 3: In-Process Best-Effort Limiter** | Hand-written sliding window counter per function container. | Zero database overhead, zero new dependencies. | Limits apply per function instance rather than globally; effective cluster limit scales with instance count. |

- **Proposed Baseline**: Implement **Option 1 (Database-Backed Counter)** for sensitive state-changing endpoints (link creation, auth), combined with **Option 3 (In-Process)** for high-throughput redirect burst defense. Operator approval is required before introducing Option 2 (Upstash).

### Database-Backed Daily Link Cap (100 links/day)
- Daily link quota is calculated using UTC calendar midnight computed in Python:
  ```python
  from datetime import datetime, timezone

  now_utc = datetime.now(timezone.utc)
  today_midnight_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
  ```
- Enforced directly via SQL query including **soft-deleted links** to prevent quota evasion by deleting links:
  ```sql
  SELECT count(*) FROM links 
  WHERE user_id = :user_id 
    AND created_at >= :today_midnight_utc;
  ```
  *(Note: Does NOT filter by `deleted_at IS NULL`; every link created today counts toward the 100 quota).*
- Rejection: Returns `HTTP 403 Forbidden` with `{"detail": "Daily link creation limit reached (100 links/day)."}`.

### Redirect Rate Limit Adjustment
- Redirect burst limit configured to **600 requests/minute per IP** (10 req/s).
- *Rationale*: Shared mobile carrier networks (CGNAT) often route hundreds of mobile users through a single public IP address; a strict 120/min limit causes false-positive blocking of innocent redirect traffic.
- Initial deployment runs in **Log-Only Mode** to observe real traffic distributions before active blocking is enabled.

---

## 7. Security Headers & Phased Rollout Strategy

### Phase 1: Content Security Policy (Report-Only)
```http
Content-Security-Policy-Report-Only: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none';
```
- **Manual Verification Checklist (5 Pages)**:
  1. [ ] Landing page (`/`) — verifies layout and styling.
  2. [ ] Login page (`/login`) — verifies OAuth action buttons.
  3. [ ] Dashboard (`/dashboard`) — verifies link creation and tables.
  4. [ ] Analytics page (`/analytics`) — verifies dynamic SVG timeseries chart rendering.
  5. [ ] Settings page (`/settings`) — verifies session tables and modals.

### Phase 2: Strict-Transport-Security (HSTS) with Rollback
- Initial setting: `Strict-Transport-Security: max-age=300` (5 minutes, no subdomains, no preload).
- Rollback procedure: If certificate issues occur, remove header or set `max-age=0`.

---

## 8. Production OAuth Setup Guide (`<project>.vercel.app`)

### Exact Callback URIs
- **Google OAuth**: `https://<project>.vercel.app/api/auth/callback/google`
- **GitHub OAuth**: `https://<project>.vercel.app/api/auth/callback/github`

### Dedicated GitHub OAuth App
- Create a dedicated GitHub OAuth app named `LinkSphere Vercel Production`.
- Homepage URL: `https://<project>.vercel.app`
- Authorization callback URL: `https://<project>.vercel.app/api/auth/callback/github`

### Google Cloud Console Consent Screen (Testing Status)
- Keep Google OAuth Consent Screen in **TESTING** status during initial rollout.
- Explicitly add the operator's Google email to the **Test users** list in Google Cloud Console.
- **Pre-Publishing Verification Checklist (Before Ever Publishing)**:
  - [ ] Live public application homepage (`https://<project>.vercel.app`) **(verify)**.
  - [ ] Live public Privacy Policy link (`https://<project>.vercel.app/privacy` or hosted document) **(verify)**.
  - [ ] Terms of Service link **(verify)**.
  - [ ] Domain ownership verified in Google Search Console if a custom apex domain is attached later.

---

## 9. Staged Rollout Sub-Levels (Spike 0 through Level 4.5d)

To de-risk the Vercel serverless platform constraints before writing full production code, work is structured into five progressive stages:

```
[ Spike 0: Feasibility Proof ]
             │
             ▼
[ Level 4.5a: Single Origin & Headers ] ──> [ Level 4.5b: Serverless Rate Limiting ]
                                                              │
                                                              ▼
[ Level 4.5d: Staging Deploy & Scaling ] <── [ Level 4.5c: vercel.json & CI Gate ]
```

### Spike 0: Minimum Deployment Feasibility Spike
A minimal deployment that proves the three primary technical risks on Vercel + Neon:
1. **Risk 1 (Function & Pooler Connectivity)**: Verify Python serverless function boots on Vercel, executes queries through Neon PgBouncer transaction pooler with `prepare_threshold=None`, and returns `GET /api/health` HTTP 200.
2. **Risk 2 (Click Durability)**: Verify synchronous insert before redirect successfully commits a click row in Neon before the function context freezes.
3. **Risk 3 (Single-Origin Rewrites & Cookies)**: Verify that hitting `/dashboard` renders the Vite frontend and that `session_token` cookie persists across requests on `https://<project>.vercel.app`.
- **Operator Manual Setup for Spike 0**:
  - Create free Vercel account and link project repository.
  - Create free Neon account, spin up a serverless PostgreSQL 16 database, and copy pooled connection string.
  - Register Google OAuth credentials (in Testing mode with operator test email).
  - Register GitHub OAuth app with callback `https://<project>.vercel.app/api/auth/callback/github`.
  - Generate 32-byte secret: `openssl rand -hex 32`.
  - Enter environment variables in Vercel Project Dashboard (`DATABASE_URL`, `SESSION_SECRET`, `ENVIRONMENT=production`, `FRONTEND_ORIGIN=https://<project>.vercel.app`, `SHORT_LINK_BASE_URL=https://<project>.vercel.app`, OAuth keys).
- **Spike 0 Acceptance Criteria**:
  - `curl -i https://<project>.vercel.app/api/health` returns HTTP 200 `{"status":"ok","database":"connected"}`.
  - Visiting a short link redirects to destination and increments Neon `click_events` count by 1.

---

### Level 4.5a: Single-Origin Routing, Reserved Words & Security Headers
- **Deliverables**:
  1. Frontend build configuration emitting static assets to `dist/`.
  2. Synchronize `RESERVED_CODES` to include `analytics` and `settings`.
  3. Implement CSP-Report-Only middleware and initial short HSTS (`max-age=300`).
  4. Response caching headers (`immutable` for hashed assets, `no-cache` for HTML/redirects).
- **Tests & Acceptance**:
  - `test_reserved_codes_cover_all_frontend_routes` passes in CI.
  - Browser console on all 5 pages verifies zero CSP violation warnings.

---

### Level 4.5b: Serverless Rate Limiting & Daily Link Cap
- **Deliverables**:
  1. Database-backed atomic fixed-window rate limiter for sensitive endpoints.
  2. Database-backed daily link cap (100 links/day per user computed using Python UTC midnight, counting soft-deleted links).
  3. Redirect rate limit set to 600 req/min per IP in log-only mode.
- **Tests & Acceptance**:
  - Unit tests verifying concurrency, window expiration, and 429 Retry-After.
  - Integration test verifying 101st link created on the same UTC day returns HTTP 403.

---

### Level 4.5c: `vercel.json` Configuration & GitHub Actions CI Gate
- **Deliverables**:
  1. Production `vercel.json` routing configuration mapping static assets, SPA routes, API functions, and short-code catch-all.
  2. GitHub Actions workflow (`.github/workflows/ci.yml`) running backend `pytest` against PostgreSQL service container `linksphere_test` and verifying `npm run build`.
- **Tests & Acceptance**:
  - CI pipeline passes with 126+ tests and zero build errors prior to any deployment trigger.

---

### Level 4.5d: Staging Deployment, Scaling Curve & Click Equality
- **Deliverables**:
  1. Deploy full application to Vercel production subdomain `https://<project>.vercel.app`.
  2. Run scaling curve verification (1, 5, 20, and 50 concurrent requests) to measure Vercel serverless cold/warm response latencies.
  3. Execute 100-request click equality validation test.
- **Tests & Acceptance**:
  - Click equality: 100 redirects produce exactly 100 rows in Neon `click_events`.
  - Full manual walkthrough: Login via Google/GitHub, create link, 5 redirects, view analytics, logout-all.

---

## 10. Open Questions for Operator

Before proceeding to implement Spike 0 or any deployment artifacts, please confirm:

1. **Neon Selection**: Do you approve using **Neon** as the serverless PostgreSQL provider, or would you prefer evaluating Supabase or Render PostgreSQL?
2. **Rate Limiting Approach**: Do you approve the proposed **Option 1 (Database-Backed atomic counter in Postgres)** for rate limiting, or do you prefer keeping it in-process (best-effort per serverless container)?
3. **Vercel Account Status**: Do you already have a Vercel account and GitHub repository integration ready for connecting the project?

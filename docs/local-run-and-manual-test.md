# LinkSphere v2 Local Run & Manual Verification Guide

This guide provides step-by-step instructions for booting the full LinkSphere v2 stack locally on a Windows development machine, executing end-to-end user workflows, and verifying database state changes via SQL.

All commands below are verified to run locally. Actions requiring real third-party OAuth provider credentials are explicitly marked as **NOT VERIFIED (Requires Real OAuth Credentials)**.

---

## 1. Prerequisites & Environment Configuration

### Step 1: Clone & Directory
Open PowerShell and navigate to the project directory:
```powershell
cd C:\Users\Shuddhodhan\LinkSphere_v2
```

### Step 2: Environment Variables (`.env`)
Create `.env` at the root of `LinkSphere_v2/` (or copy `.env.example`).
> **Security Note:** Never commit `.env` or store real secrets in documentation.

Required environment variable keys (names only, matching `app/core/config.py` and `.env.example`):
* `POSTGRES_DB`
* `POSTGRES_USER`
* `POSTGRES_PASSWORD`
* `POSTGRES_HOST`
* `POSTGRES_PORT`
* `DATABASE_URL` (e.g. `postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_db`)
* `CORS_ORIGINS` (e.g. `http://localhost:5173,http://localhost:5174`)
* `FRONTEND_ORIGIN` (`http://localhost:5173`)
* `ENVIRONMENT` (`local`)
* `GOOGLE_CLIENT_ID`
* `GOOGLE_CLIENT_SECRET`
* `GITHUB_CLIENT_ID`
* `GITHUB_CLIENT_SECRET`
* `SESSION_SECRET`
* `SESSION_LIFETIME_DAYS` (`7`)
* `SESSION_IDLE_TIMEOUT_HOURS` (`24`)
* `SHORT_LINK_BASE_URL` (`http://localhost:8001`)
* `DB_POOL_SIZE`
* `DB_MAX_OVERFLOW`
* `DB_POOL_TIMEOUT`

---

## 2. Infrastructure & Database Initialization

### Step 3: Start PostgreSQL 16 via Docker Compose
Start the dedicated database container in the background using service `db` defined in `docker-compose.yml`:
```powershell
docker compose up -d db
```
* **Service Name in `docker-compose.yml`:** `db`
* **Container Name:** `linksphere-v2-db`
* **Exposed Port:** `5434` (mapped to PostgreSQL internal `5432` to avoid host conflicts)
* **Verification Command:**
  ```powershell
  docker ps --filter "name=linksphere-v2-db"
  ```
  *(Status should report `Up (healthy)`)*

### Step 4: Apply Database Migrations
Run Alembic migrations to apply all schema revisions to the current head:
```powershell
cd C:\Users\Shuddhodhan\LinkSphere_v2\backend
.\.venv\Scripts\alembic.exe upgrade head
```
* **Verification Command:**
  ```powershell
  .\.venv\Scripts\alembic.exe current
  ```
  *(Expected Output: `0002_add_deleted_at_to_links (head)`)*

---

## 3. Starting Services

### Step 5: Start FastAPI Backend
In a separate terminal or background process:
```powershell
cd C:\Users\Shuddhodhan\LinkSphere_v2\backend
$env:ENVIRONMENT = "local"
.\.venv\Scripts\uvicorn.exe app.main:app --host localhost --port 8001
```
* **Backend URL:** `http://localhost:8001`
* **Health Check Verification (Direct):**
  ```powershell
  curl.exe -i http://localhost:8001/api/health
  # Expected response: HTTP/1.1 200 OK {"status":"ok","database":"connected"}
  ```

### Step 6: Start React / Vite Frontend
In a separate terminal:
```powershell
cd C:\Users\Shuddhodhan\LinkSphere_v2\frontend
npm run dev
```
* **Frontend URL:** `http://localhost:5173`
* **Proxy Health Check Verification (via Vite proxy `/api` -> `http://localhost:8001`):**
  ```powershell
  curl.exe -i http://localhost:5173/api/health
  # Expected response: HTTP/1.1 200 OK {"status":"ok","database":"connected"}
  ```
* **Frontend Build Check:**
  ```powershell
  npm run build
  # Expected: "✓ built in ...s" with 48 modules transformed
  ```

---

## 4. End-to-End Manual Workflow Walkthrough & SQL Verification

Connect to the PostgreSQL database for verification using `psql` or `docker exec`:
```powershell
docker exec -it linksphere-v2-db psql -U linksphere_user -d linksphere_db
```

### Scenario A: Google Sign-Up & Login
1. In the browser, navigate to `http://localhost:5173/login`.
2. Click **Continue with Google**.
   * *Status:* **NOT VERIFIED (Requires Real OAuth Credentials)**
3. Upon returning from Google, you are redirected to `http://localhost:5173/dashboard`.
4. **SQL Verification:**
   ```sql
   SELECT id, email, name FROM users;
   -- Expected: 1 row with your Google account email and name

   SELECT id, provider, provider_user_id, email_verified FROM auth_identities;
   -- Expected: 1 row with provider = 'google', email_verified = true

   SELECT id, user_id, revoked_at, expires_at FROM sessions;
   -- Expected: 1 active session where revoked_at IS NULL and expires_at > NOW()
   ```

### Scenario B: Sign Out
1. On `/dashboard`, click **Sign Out** or click your profile avatar and select Sign Out.
2. Observe redirection to `/login`.
3. Try directly accessing `http://localhost:5173/dashboard` in the address bar.
   * *Verification:* Automatically redirects back to `/login` because `session_token` cookie is cleared.
4. **SQL Verification:**
   ```sql
   SELECT id, revoked_at FROM sessions ORDER BY created_at DESC LIMIT 1;
   -- Expected: revoked_at is populated with the logout timestamp
   ```

### Scenario C: GitHub Sign-In Account Linking
1. While logged out, click **Continue with GitHub** on `http://localhost:5173/login` using the same email address as Google.
   * *Status:* **NOT VERIFIED (Requires Real OAuth Credentials)**
2. Upon authentication, you are redirected to `http://localhost:5173/dashboard`.
3. Navigate to `http://localhost:5173/settings`.
4. **UI Check:** Under "Connected Accounts", both Google and GitHub appear as connected.
5. **SQL Verification:**
   ```sql
   SELECT count(*) FROM users WHERE email = '<your_email>';
   -- Expected: Exactly 1 (no duplicate user created)

   SELECT count(*) FROM auth_identities WHERE user_id = (SELECT id FROM users WHERE email = '<your_email>');
   -- Expected: Exactly 2 (one 'google', one 'github')
   ```

### Scenario D: Link Creation
1. On `http://localhost:5173/dashboard`, enter a target URL (e.g., `https://example.com/docs`) and click **Create Link**.
2. Note the generated short code (e.g. `k8s9x2`).
3. **SQL Verification:**
   ```sql
   SELECT id, short_code, original_url, click_count, is_active FROM links WHERE short_code = 'k8s9x2';
   -- Expected: click_count = 0, is_active = true, deleted_at IS NULL
   ```

### Scenario E: 5 Short URL Redirects
1. Using PowerShell, issue 5 requests to the redirect URL on port 8001:
   ```powershell
   1..5 | ForEach-Object {
       curl.exe -s -o NUL -w "%{http_code}`n" http://localhost:8001/k8s9x2
   }
   # Expected: Five 302 HTTP status codes
   ```
2. **SQL Verification:**
   ```sql
   SELECT count(*) FROM click_events WHERE link_id = (SELECT id FROM links WHERE short_code = 'k8s9x2');
   -- Expected: Exactly 5

   SELECT click_count FROM links WHERE short_code = 'k8s9x2';
   -- Expected: 5
   ```

### Scenario F: Analytics Verification (7, 30, and 90 Days)
1. In the browser, navigate to `http://localhost:5173/analytics`.
2. Select the created link from the dropdown (or view aggregate analytics).
3. **UI Check:** Total Clicks displays `5`.
4. Toggle between the **7 Days**, **30 Days**, and **90 Days** range filters.
5. Verify timeseries buckets reflect the 5 clicks recorded today without timezone mismatch or missing buckets.
6. Verify referrer and device breakdown sections display the request client headers.

### Scenario G: "Sign Out Everywhere" (Multi-Session Revocation)
1. Open a second browser or incognito window, navigate to `http://localhost:5173/login`, and log in.
2. In window 1, open `http://localhost:5173/settings`.
3. Under "Active Sessions", verify 2 sessions are listed, with the current browser session marked with the "Current Session" badge.
4. Click **Sign Out Everywhere**.
5. Both sessions are revoked.
6. Refresh or navigate in window 2; verify window 2 immediately redirects to `/login` with HTTP 401 on background requests.
7. **SQL Verification:**
   ```sql
   SELECT count(*) FROM sessions
   WHERE user_id = (SELECT id FROM users WHERE email = '<your_email>')
     AND revoked_at IS NULL;
   -- Expected: 0
   ```

### Scenario H: Link Deletion
1. In the primary browser, log in again and navigate to `/dashboard`.
2. Click **Delete** on the link `k8s9x2`.
3. Confirm link is removed from the dashboard links list.
4. Attempt visiting `http://localhost:8001/k8s9x2` in browser or curl.exe:
   ```powershell
   curl.exe -i http://localhost:8001/k8s9x2
   # Expected: HTTP/1.1 404 Not Found (custom 404 HTML response)
   ```
5. **SQL Verification:**
   ```sql
   SELECT id, short_code, is_active, deleted_at FROM links WHERE short_code = 'k8s9x2';
   -- Expected: is_active = false, deleted_at IS NOT NULL (soft deleted; short code remains reserved)
   ```

---

## 5. Summary of Automated Verification Commands

| Component | Verification Command | Verified Status |
| :--- | :--- | :--- |
| **PostgreSQL Database** | `docker ps --filter "name=linksphere-v2-db"` | VERIFIED (`Up (healthy)`) |
| **Alembic Schema** | `.\.venv\Scripts\alembic.exe current` | VERIFIED (`0002_add_deleted_at_to_links`) |
| **Backend Health (Direct)** | `curl.exe -i http://localhost:8001/api/health` | VERIFIED (`HTTP/1.1 200 OK`) |
| **Frontend Health (Vite Proxy)** | `curl.exe -i http://localhost:5173/api/health` | VERIFIED (`HTTP/1.1 200 OK`) |
| **Backend Test Suite** | `.\.venv\Scripts\pytest.exe` | VERIFIED (126 passed, 1 warning) |
| **Frontend Production Build** | `npm run build` | VERIFIED (48 modules transformed, 0 errors) |
| **OAuth Third-Party Providers** | Google / GitHub interactive sign-in | NOT VERIFIED (Requires Real OAuth Credentials) |

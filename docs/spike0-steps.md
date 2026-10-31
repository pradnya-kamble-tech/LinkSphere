# Spike 0: Vercel & Neon Feasibility Verification Guide

This guide provides the exact operator walkthrough for running **Spike 0** on Vercel and Neon, as well as the commands for local development verification.

---

## 1. Operator Manual Setup (Neon & Vercel)

### Step 1: Provision Neon PostgreSQL 16
1. Log in to [Neon Console](https://console.neon.tech).
2. Create a new project:
   - **Project Name**: `linksphere-spike`
   - **Postgres Version**: `16`
   - **Region**: Select **AWS `us-east-1` (N. Virginia)** *(matches Vercel `iad1` default)*.
3. Open the **SQL Editor** tab in Neon console.
4. Paste and execute the contents of [`spike/schema.sql`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/spike/schema.sql):
   ```sql
   CREATE TABLE IF NOT EXISTS spike_clicks (
       id SERIAL PRIMARY KEY,
       code VARCHAR(50) NOT NULL,
       kind VARCHAR(20) NOT NULL,
       clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
   );
   CREATE INDEX IF NOT EXISTS idx_spike_clicks_kind ON spike_clicks(kind);
   ```
5. From the Neon Dashboard, copy the **Pooled connection string** (ends with `-pooler.region.aws.neon.tech` on port 5432).

### Step 2: Configure & Deploy on Vercel
1. Log in to [Vercel Dashboard](https://vercel.com).
2. Click **Add New...** $\rightarrow$ **Project** $\rightarrow$ Import your GitHub repository (`LinkSphere`).
3. Configure Project Settings:
   - **Framework Preset**: `Other`
   - **Root Directory**: `spike`
   - **Production Branch**: Set to `spike/vercel` (for this feasibility test).
4. Environment Variables (Settings $\rightarrow$ Environment Variables):
   - `DATABASE_URL`: Paste the Neon **pooled** connection string (ensure it uses `postgresql+psycopg://...`).
   - `ENVIRONMENT`: `production`
   - `COOKIE_SECURE`: `true`
5. **Deployment Protection Note**:
   - Navigate to **Settings** $\rightarrow$ **Deployment Protection**.
   - Ensure "Vercel Authentication" is **Disabled** for production deployments so public HTTP requests and OAuth redirects are not blocked by a Vercel login screen.
6. Click **Deploy**. Note your generated project URL: `https://<project>.vercel.app`.

---

## 2. Acceptance Verification Tests (PowerShell using `curl.exe`)

Run these tests in PowerShell against your deployed Vercel domain (`https://<project>.vercel.app`).
*(For local testing, replace `https://<project>.vercel.app` with `http://localhost:8002`)*.

### Test A: Database Ping & Region Latency
```powershell
curl.exe -s -i "https://<project>.vercel.app/api/spike/db"
```
*Expected*: HTTP 200 with JSON payload containing `"database": "connected"`, `"elapsed_ms"`, and `"vercel_region": "iad1"`.

---

### Test B: 100 Synchronous Redirects & Count Check
Issue 100 synchronous redirect requests to measure latency and verify click durability:
```powershell
Write-Host "Issuing 100 synchronous redirects..."
1..100 | ForEach-Object {
    curl.exe -s -o NUL -w "%{http_code}`n" "https://<project>.vercel.app/sync-$_"
}

# Verify counts immediately:
curl.exe -s "https://<project>.vercel.app/api/spike/count"
```
*Expected*:
- All 100 requests return HTTP `302`.
- `/api/spike/count` immediately shows `{"sync": 100, "background": 0}`.

---

### Test C: 100 Background-Task Redirects & Survivability Check
Issue 100 background-task redirect requests, wait 10 seconds, and measure how many background tasks survived before the serverless CPU context froze:
```powershell
Write-Host "Issuing 100 background-task redirects..."
1..100 | ForEach-Object {
    curl.exe -s -o NUL -w "%{http_code}`n" "https://<project>.vercel.app/bg/bg-$_"
}

Write-Host "Waiting 10 seconds for any delayed background tasks..."
Start-Sleep -Seconds 10

# Check count to see if background tasks survived:
curl.exe -s "https://<project>.vercel.app/api/spike/count"
```
*Observation*:
- If `"background": 100`, background tasks survived.
- If `"background" < 100` (or 0), AWS Lambda/Vercel froze the CPU context immediately upon response return, confirming background execution is unsafe in serverless.

---

### Test D: Neon Cold-Start & Autosuspend Wakeup Test
1. Allow the database to remain completely idle for **10+ minutes** (allowing Neon compute to autosuspend).
2. Measure the response time of the very first request to wake up compute:
   ```powershell
   Measure-Command {
       $res = curl.exe -s -w "%{http_code}" "https://<project>.vercel.app/api/spike/db"
       Write-Host "HTTP Status: $res"
   }
   ```
*Expected*: Status 200, execution time records between 800ms and 3000ms (reflecting Neon compute cold boot).

---

### Test E: Same-Origin Cookie Verification
Test setting and reading an `HttpOnly`, `SameSite=Lax`, `Secure` cookie on the same origin:
```powershell
# 1. Set cookie and save jar
curl.exe -s -c cookie.txt "https://<project>.vercel.app/api/spike/cookie-set"

# 2. Read cookie back using saved jar
curl.exe -s -b cookie.txt "https://<project>.vercel.app/api/spike/cookie-read"

# 3. Clean up cookie jar
Remove-Item cookie.txt
```
*Expected*:
- `cookie-set` returns `{"status":"cookie_set","cookie":"spike_session"}`.
- `cookie-read` returns `{"cookie_found": true, "cookie_value": "spike_token_abc123_verified"}`.

---

## 3. Results Recording Template

Record your live test measurements below:

| Metric / Scenario | Local Verification Status | Vercel + Neon Staging (Operator) | Notes |
| :--- | :--- | :--- | :--- |
| **Database Ping (`/api/spike/db`)** | **VERIFIED (Local)** | *(Fill: elapsed_ms & region)* | Target: < 40 ms warm in-region |
| **Sync 100 Redirects Count** | **VERIFIED (100 / 100)** | *(Fill: sync count)* | Must be exactly 100 |
| **Background 100 Redirects Count** | **VERIFIED (100 / 100 on local)** | *(Fill: bg count)* | **CRITICAL**: If < 100, proves Lambda freeze |
| **Neon Autosuspend Wake Time** | **NOT APPLICABLE (Local)** | *(Fill: seconds to wake)* | Measured after 10m idle |
| **Same-Origin Cookie Read/Write** | **VERIFIED (Local)** | *(Fill: OK / Blocked)* | Must return `cookie_found: true` |
| **Deployment Protection Status** | **NOT APPLICABLE (Local)** | *(Fill: Disabled / Bypassed)* | Must allow public 302 redirects |

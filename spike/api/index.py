import os
import time
from typing import Dict, Any
from fastapi import FastAPI, BackgroundTasks, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

app = FastAPI(title="LinkSphere Spike 0")

def get_engine():
    """Create SQLAlchemy engine using NullPool and prepare_threshold=None for transaction pooler compatibility."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not configured.")
    return create_engine(
        db_url,
        poolclass=NullPool,
        connect_args={"prepare_threshold": None},
    )

# -----------------------------------------------------------------------------
# 1. Database Ping & Region Detection
# -----------------------------------------------------------------------------
@app.get("/api/spike/db")
def spike_db():
    start = time.perf_counter()
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1;"))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "status": "ok",
        "database": "connected",
        "elapsed_ms": round(elapsed_ms, 2),
        "vercel_region": os.environ.get("VERCEL_REGION", "local"),
    }

# -----------------------------------------------------------------------------
# 2. Static / Login Page Serving (Local Development & Fallback)
# -----------------------------------------------------------------------------
STATIC_INDEX = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def serve_index():
    if os.path.exists(STATIC_INDEX):
        with open(STATIC_INDEX, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>LinkSphere Spike 0</h1><p>Static index.html not found.</p>"

# -----------------------------------------------------------------------------
# 3. Background Task Redirect (Insert after response)
# -----------------------------------------------------------------------------
def _bg_insert_task(code: str):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO spike_clicks (code, kind) VALUES (:code, :kind);"),
                {"code": code, "kind": "background"},
            )
    except Exception as e:
        print(f"Background task insertion failed: {e}")

@app.get("/bg/{code}")
def bg_redirect(code: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_bg_insert_task, code)
    return RedirectResponse("https://example.com", status_code=status.HTTP_302_FOUND)

# -----------------------------------------------------------------------------
# 4. Synchronous Redirect (Catch-all: Commit before response)
# -----------------------------------------------------------------------------
@app.get("/{code}")
def sync_redirect(code: str):
    if code in ("favicon.ico", "robots.txt", "index.html", "api"):
        raise HTTPException(status_code=404, detail="Not a short code")
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO spike_clicks (code, kind) VALUES (:code, :kind);"),
            {"code": code, "kind": "sync"},
        )
    return RedirectResponse("https://example.com", status_code=status.HTTP_302_FOUND)


# -----------------------------------------------------------------------------
# 4. Click Event Counter
# -----------------------------------------------------------------------------
@app.get("/api/spike/count")
def spike_count() -> Dict[str, int]:
    engine = get_engine()
    counts = {"sync": 0, "background": 0}
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kind, count(*) FROM spike_clicks GROUP BY kind;")
        ).fetchall()
        for kind, cnt in rows:
            if kind in counts:
                counts[kind] = int(cnt)
    return counts

# -----------------------------------------------------------------------------
# 5. Same-Origin Cookie Verification
# -----------------------------------------------------------------------------
@app.get("/api/spike/cookie-set")
def spike_cookie_set(response: Response):
    # Cookie is HttpOnly, SameSite=Lax, Secure (in production/https)
    is_secure = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    response.set_cookie(
        key="spike_session",
        value="spike_token_abc123_verified",
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
    )
    return {"status": "cookie_set", "cookie": "spike_session"}

@app.get("/api/spike/cookie-read")
def spike_cookie_read(request: Request):
    val = request.cookies.get("spike_session")
    return {
        "cookie_found": bool(val),
        "cookie_value": val if val else None,
    }


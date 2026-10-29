from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.links.models import Link
from app.analytics.service import record_click_background

router = APIRouter(tags=["redirect"])

HTML_404 = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Link Not Found - LinkSphere</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .card { max-width: 440px; padding: 2rem; background: #1e293b; border-radius: 8px; border: 1px solid #334155; text-align: center; }
        h1 { margin-top: 0; color: #ef4444; font-size: 1.5rem; }
        p { color: #94a3b8; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="card">
        <h1>404 - Link Not Found</h1>
        <p>The short link you followed does not exist, has been disabled, or was removed.</p>
    </div>
</body>
</html>"""

HTML_410 = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Link Expired - LinkSphere</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .card { max-width: 440px; padding: 2rem; background: #1e293b; border-radius: 8px; border: 1px solid #334155; text-align: center; }
        h1 { margin-top: 0; color: #f59e0b; font-size: 1.5rem; }
        p { color: #94a3b8; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="card">
        <h1>410 - Link Expired</h1>
        <p>This link has reached its expiration date and is no longer accessible.</p>
    </div>
</body>
</html>"""


@router.api_route("/{short_code}", methods=["GET", "HEAD"])
def redirect_to_url(
    short_code: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Ultra-lean redirect handler:
    - Single indexed query using raw SQLAlchemy Core select.
    - Zero unnecessary ORM entity tracking.
    - 302 Found with Cache-Control: no-store.
    - HEAD requests redirect without logging click.
    - GET requests log click asynchronously via BackgroundTask with independent DB session.
    - Unknown, inactive, and deleted return 404 HTML page.
    - Expired links return 410 HTML page.
    """
    stmt = (
        select(Link.id, Link.original_url, Link.is_active, Link.expires_at, Link.deleted_at)
        .where(Link.short_code == short_code)
    )
    row = db.execute(stmt).first()

    # 1. Unknown or deleted or inactive -> 404 HTML
    if not row or row.deleted_at is not None or not row.is_active:
        return HTMLResponse(content=HTML_404, status_code=404)

    # 2. Expired -> 410 HTML
    now_utc = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now_utc:
        return HTMLResponse(content=HTML_410, status_code=410)

    # 3. Valid redirect: 302 with Cache-Control: no-store
    headers = {"Cache-Control": "no-store"}

    if request.method.upper() == "HEAD":
        # HEAD requests redirect but record NO click
        return RedirectResponse(url=row.original_url, status_code=302, headers=headers)

    # GET requests record click asynchronously
    bg_task = BackgroundTask(
        record_click_background,
        link_id=row.id,
        referrer=request.headers.get("referer"),
        user_agent=request.headers.get("user-agent"),
    )
    return RedirectResponse(
        url=row.original_url,
        status_code=302,
        headers=headers,
        background=bg_task,
    )

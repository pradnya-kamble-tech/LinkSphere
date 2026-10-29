from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import anyio
from app.core.config import settings

# Ensure all SQLAlchemy models are registered
import app.users.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.links.models  # noqa: F401
import app.analytics.models  # noqa: F401

from app.api.health import router as health_router
from app.auth.router import router as auth_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Increase AnyIO capacity limiter from default 40 to 200 to prevent threadpool starvation under concurrency
    anyio.to_thread.current_default_thread_limiter().total_tokens = 200
    yield


app = FastAPI(title="LinkSphere API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes under /api
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")

# Also maintain /health for backward compatibility
app.include_router(health_router)





# Gated diagnostic endpoints: strictly available only when ENVIRONMENT=test
if settings.ENVIRONMENT.lower() == "test":
    @app.get("/api/diagnostic/ping-async")
    async def diagnostic_ping_async():
        """Trivial async endpoint without database access for diagnosing framework latency."""
        return {"status": "ok"}

    @app.get("/api/diagnostic/ping-sync")
    def diagnostic_ping_sync():
        """Trivial sync endpoint (threadpool) without database access for diagnosing threadpool latency."""
        return {"status": "ok"}

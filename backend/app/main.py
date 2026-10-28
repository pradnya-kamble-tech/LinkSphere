from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

# Ensure all SQLAlchemy models are registered
import app.users.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.links.models  # noqa: F401
import app.analytics.models  # noqa: F401

from app.api.health import router as health_router
from app.auth.router import router as auth_router
from app.users.router import router as users_router

app = FastAPI(title="LinkSphere API")

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

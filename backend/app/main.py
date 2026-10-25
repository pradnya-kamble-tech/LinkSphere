from fastapi import FastAPI

from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    description="A URL shortener and link analytics platform.",
    version=settings.app_version,
)


@app.get("/")
def read_root():
    return {
        "message": "Welcome to LinkSphere API!",
        "status": "running",
        "environment": settings.environment,
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "linksphere-api",
        "environment": settings.environment,
    }

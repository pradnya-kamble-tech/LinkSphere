import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import SessionLocal
from app.api.health import health_check


def test_health_healthy():
    """Verify health_check returns 200 format when database is reachable."""
    db = SessionLocal()
    try:
        res = health_check(db)
        assert res == {"status": "ok", "database": "connected"}
    finally:
        db.close()


def test_health_unhealthy():
    """Verify health_check raises HTTP 503 with details when database fails."""
    broken_engine = create_engine("postgresql+psycopg://baduser:badpass@127.0.0.1:5434/baddb")
    BrokenSession = sessionmaker(bind=broken_engine)
    db = BrokenSession()
    try:
        with pytest.raises(HTTPException) as exc_info:
            health_check(db)
        assert exc_info.value.status_code == 503
        assert "Database connection failed" in exc_info.value.detail
    finally:
        db.close()

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command
import httpx

# Set dummy OAuth environment values for tests per Amendment 9
os.environ["ENVIRONMENT"] = "test"
os.environ["GOOGLE_CLIENT_ID"] = "dummy_test_google_client_id"
os.environ["GOOGLE_CLIENT_SECRET"] = "dummy_test_google_client_secret"
os.environ["GITHUB_CLIENT_ID"] = "dummy_test_github_client_id"
os.environ["GITHUB_CLIENT_SECRET"] = "dummy_test_github_client_secret"
os.environ["SESSION_SECRET"] = "dummy_test_session_secret_32_bytes_long_ok"

from app.core.config import settings
from app.main import app

# Test database settings
TEST_DB_NAME = "linksphere_test"

# Verify safety rule: Must end in _test
if not TEST_DB_NAME.endswith("_test"):
    raise RuntimeError(f"ABORT: Test database name '{TEST_DB_NAME}' does not end in '_test'!")

# Parse base URL to connect to administrative postgres database
base_url_parts = settings.DATABASE_URL.rsplit("/", 1)
ADMIN_DB_URL = f"{base_url_parts[0]}/postgres"
TEST_DATABASE_URL = f"{base_url_parts[0]}/{TEST_DB_NAME}"


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure linksphere_test database exists and is migrated to head."""
    # Safety assertion
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"ABORT: Safety check failed! Target database '{db_name}' does not end in '_test'.")

    # Connect to postgres server to create test database if not exists
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT 1 FROM pg_database WHERE datname = '{TEST_DB_NAME}'")
        )
        if not result.scalar():
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()

    # Run alembic migrations into the test database
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    yield


@pytest.fixture(scope="session")
def test_engine(setup_test_database):
    # Enforce safety check
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
    assert db_name.endswith("_test"), "ABORT: Attempting to connect to non-test database!"

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def TestSessionLocal(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db(TestSessionLocal, test_engine):
    """Provides a transactional database session that cleans up after each test."""
    db_name = test_engine.url.database
    assert db_name.endswith("_test"), f"ABORT: Test session connected to '{db_name}'!"

    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        # Clean data from tables in reverse dependency order
        with test_engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE click_events, links, sessions, auth_identities, users RESTART IDENTITY CASCADE"))
            conn.commit()
        session.close()


@pytest.fixture
def alembic_test_cfg():
    """Provides Alembic config pointed strictly to the test database."""
    assert TEST_DATABASE_URL.rsplit("/", 1)[-1].endswith("_test")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


@pytest.fixture
async def async_client(db):
    """Async client connected to the FastAPI app using the test database."""
    from app.core.db import get_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:5173") as client:
        yield client
    app.dependency_overrides.clear()

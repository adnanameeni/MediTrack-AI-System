import os

# These must be set BEFORE any app code is imported.
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-real-use-0123456789"
# Tests must never touch a real database, even if DATABASE_URL is set in the
# shell or in .env (for example while moving data to PostgreSQL).
os.environ["DATABASE_URL"] = "sqlite://"

# Optional: set TEST_DATABASE_URL to a PostgreSQL URL to run the whole test
# suite against PostgreSQL instead of the default in-memory SQLite database.
# Example (PowerShell):
#   $env:TEST_DATABASE_URL = "postgresql+psycopg://user:pass@localhost/meditrack_test"
# The tables in that database are DROPPED and re-created for every test, so it
# must be a throw-away database. Its name has to contain "test".
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.database.session import normalize_database_url
from main import app


def _postgres_test_engine():
    url = make_url(normalize_database_url(TEST_DATABASE_URL))
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must be a PostgreSQL URL.")
    if "test" not in (url.database or "").lower():
        raise RuntimeError(
            "Refusing to run: the tests DROP every table in TEST_DATABASE_URL, "
            "so the database name must contain 'test'."
        )
    return create_engine(url, pool_pre_ping=True)


@pytest.fixture()
def db_session():
    if TEST_DATABASE_URL:
        engine = _postgres_test_engine()
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        if TEST_DATABASE_URL:
            Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

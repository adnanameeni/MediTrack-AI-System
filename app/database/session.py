import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def normalize_database_url(url: str) -> str:
    """Tidy a database URL so it always uses the driver this project installs.

    - Surrounding spaces and quotes are removed (easy to paste by accident
      into a hosting dashboard).
    - postgres:// and postgresql:// become postgresql+psycopg://, which is
      Psycopg 3. Nothing else in the URL is touched, so the user name,
      password and ?sslmode=require stay exactly as given.
    - SQLite and any other URL is returned unchanged.
    """
    url = url.strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in ("'", '"'):
        url = url[1:-1].strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _engine_options(url: str) -> dict:
    """Engine settings for each kind of database."""
    if url.startswith("sqlite"):
        # Same settings the project has always used for SQLite.
        return {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }

    options = {
        "pool_pre_ping": True,  # replace a connection the server closed
        "pool_recycle": 300,  # serverless databases close idle connections
        "pool_size": 3,  # small: every serverless instance has its own pool
        "max_overflow": 2,
    }
    if url.startswith("postgresql"):
        options["connect_args"] = {
            "connect_timeout": 10,
            # Poolers such as Neon's "-pooler" address do not support
            # server-side prepared statements, so switch them off.
            "prepare_threshold": None,
        }
    return options


_raw_database_url = os.getenv("DATABASE_URL")

if not _raw_database_url or not _raw_database_url.strip():
    raise RuntimeError("DATABASE_URL is not set")

DATABASE_URL = normalize_database_url(_raw_database_url)

engine = create_engine(DATABASE_URL, **_engine_options(DATABASE_URL))

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if engine.dialect.name != "sqlite":
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

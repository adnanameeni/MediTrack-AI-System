"""How DATABASE_URL is read and turned into an engine (no database needed)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.database.session import _engine_options, normalize_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEON_STYLE = "postgresql://app_user:pa55word@ep-example-123-pooler.eu-west-2.aws.neon.tech/meditrack?sslmode=require"


def test_postgresql_url_uses_psycopg_3():
    assert normalize_database_url(NEON_STYLE) == NEON_STYLE.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def test_postgres_scheme_is_accepted_too():
    result = normalize_database_url("postgres://u:p@host/db?sslmode=require")
    assert result == "postgresql+psycopg://u:p@host/db?sslmode=require"


def test_a_url_that_already_names_the_driver_is_unchanged():
    url = "postgresql+psycopg://u:p@host/db?sslmode=require"
    assert normalize_database_url(url) == url


def test_everything_after_the_scheme_is_left_exactly_as_given():
    url = "postgresql://us%40er:p%2Fw%3Fd@host:5432/db?sslmode=require&channel_binding=require"
    assert normalize_database_url(url).endswith(
        "us%40er:p%2Fw%3Fd@host:5432/db?sslmode=require&channel_binding=require"
    )


@pytest.mark.parametrize("pasted", [f'"{NEON_STYLE}"', f"'{NEON_STYLE}'", f"  {NEON_STYLE}  \n"])
def test_quotes_and_spaces_pasted_into_a_dashboard_are_removed(pasted):
    assert normalize_database_url(pasted).startswith("postgresql+psycopg://app_user:")
    assert normalize_database_url(pasted).endswith("sslmode=require")


@pytest.mark.parametrize(
    "url", ["sqlite://", "sqlite:///./meditrack.db", "sqlite:////var/data/meditrack.db"]
)
def test_sqlite_urls_are_not_changed(url):
    assert normalize_database_url(url) == url


def test_sqlite_engine_settings_are_the_ones_the_project_always_used():
    options = _engine_options("sqlite:///./meditrack.db")
    assert options == {"connect_args": {"check_same_thread": False}, "pool_pre_ping": True}


def test_postgresql_engine_settings_suit_a_serverless_host():
    options = _engine_options("postgresql+psycopg://u:p@host/db")
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] <= 300  # idle connections are closed by the host
    assert options["pool_size"] + options["max_overflow"] <= 10  # small per-instance pool
    assert options["connect_args"]["prepare_threshold"] is None  # safe behind a pooler
    assert options["connect_args"]["connect_timeout"] > 0
    assert "check_same_thread" not in options["connect_args"]


def test_postgresql_engine_can_be_built_without_connecting():
    url = normalize_database_url("postgres://u:p@localhost/db?sslmode=require")
    engine = create_engine(url, **_engine_options(url))
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def _import_session_with(database_url: str) -> subprocess.CompletedProcess:
    """Import the real session module in a clean process with this DATABASE_URL."""
    environment = dict(os.environ)
    environment["DATABASE_URL"] = database_url
    environment["SECRET_KEY"] = "test-only-secret-key-not-for-real-use-0123456789"
    code = (
        "from app.database import session; "
        "print(session.engine.dialect.name, session.engine.dialect.driver)"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_app_starts_with_a_neon_style_url():
    result = _import_session_with(NEON_STYLE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "postgresql psycopg"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_missing_or_blank_database_url_stops_the_app_with_a_clear_message(blank):
    result = _import_session_with(blank)
    assert result.returncode != 0
    assert "DATABASE_URL is not set" in result.stderr

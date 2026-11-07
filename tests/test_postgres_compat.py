"""Checks that only make sense on a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL points at a PostgreSQL TEST database, e.g.
  $env:TEST_DATABASE_URL = "postgresql+psycopg://user:pass@localhost/meditrack_test"
In that mode the db_session and client fixtures (tests/conftest.py) use
PostgreSQL, so the rest of the test suite also runs against it.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url

from app.database import Base
from app.database.session import _engine_options, normalize_database_url
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to a PostgreSQL test database"
)

PASSWORD = "Example-Pass-123"


def add_user(db, email="pg@example.com", **extra):
    user = User(full_name="Pg Person", email=email, hashed_password="HASH", **extra)
    db.add(user)
    db.commit()
    return user


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_this_really_is_postgresql(db_session):
    assert db_session.get_bind().dialect.name == "postgresql"
    assert db_session.get_bind().dialect.driver == "psycopg"


def test_every_table_is_created(db_session):
    tables = set(inspect(db_session.get_bind()).get_table_names())
    assert tables == {table.name for table in Base.metadata.sorted_tables}
    assert {"users", "glucose_readings", "blood_pressure_readings",
            "chat_conversations", "chat_messages", "admin_audit_log"} <= tables


def test_constraints_and_indexes_exist(db_session):
    inspector = inspect(db_session.get_bind())
    checks = {c["name"] for t in ("users", "blood_pressure_readings", "glucose_readings", "chat_messages")
              for c in inspector.get_check_constraints(t)}
    assert {"ck_users_role", "ck_blood_pressure_readings_systolic_gt_diastolic",
            "ck_glucose_readings_glucose_value_positive", "ck_chat_messages_role"} <= checks
    email_unique = [i for i in inspector.get_indexes("users") if i["column_names"] == ["email"]]
    assert email_unique and email_unique[0]["unique"]


def test_deleting_a_user_cascades_in_the_database(db_session):
    foreign_keys = inspect(db_session.get_bind()).get_foreign_keys("glucose_readings")
    assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
    audit = inspect(db_session.get_bind()).get_foreign_keys("admin_audit_log")
    assert {fk["options"].get("ondelete") for fk in audit} == {"SET NULL"}


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_server_defaults_work(db_session):
    db_session.execute(
        text("INSERT INTO users (full_name, email, hashed_password) VALUES ('A', 'raw@example.com', 'H')")
    )
    db_session.commit()
    row = db_session.execute(
        text("SELECT is_active, role, created_at FROM users WHERE email = 'raw@example.com'")
    ).one()
    assert row.is_active is True
    assert row.role == "user"
    assert row.created_at.tzinfo is not None
    assert abs(datetime.now(timezone.utc) - row.created_at) < timedelta(minutes=5)


def test_the_database_itself_enforces_the_rules(db_session):
    user = add_user(db_session)
    bad_statements = [
        "INSERT INTO users (full_name, email, hashed_password, role) VALUES ('x', 'r@example.com', 'h', 'superadmin')",
        f"INSERT INTO blood_pressure_readings (user_id, systolic, diastolic) VALUES ({user.id}, 80, 120)",
        f"INSERT INTO blood_pressure_readings (user_id, systolic, diastolic, pulse) VALUES ({user.id}, 120, 80, 0)",
        f"INSERT INTO glucose_readings (user_id, glucose_value, reading_type) VALUES ({user.id}, 0, 'fasting')",
        f"INSERT INTO glucose_readings (user_id, glucose_value, reading_type) VALUES ({user.id}, 90, 'bedtime')",
        "INSERT INTO glucose_readings (user_id, glucose_value, reading_type) VALUES (999999, 90, 'fasting')",
    ]
    for statement in bad_statements:
        with pytest.raises(IntegrityError):
            db_session.execute(text(statement))
        db_session.rollback()


def test_email_must_be_unique(db_session):
    add_user(db_session, "same@example.com")
    with pytest.raises(IntegrityError):
        add_user(db_session, "same@example.com")
    db_session.rollback()


def test_deleting_a_user_removes_their_readings_in_the_database(db_session):
    user = add_user(db_session)
    db_session.add(GlucoseReading(user_id=user.id, glucose_value=Decimal("95.5"), reading_type=ReadingType.FASTING))
    db_session.add(BloodPressureReading(user_id=user.id, systolic=120, diastolic=80))
    db_session.commit()

    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db_session.commit()

    assert db_session.execute(text("SELECT COUNT(*) FROM glucose_readings")).scalar_one() == 0
    assert db_session.execute(text("SELECT COUNT(*) FROM blood_pressure_readings")).scalar_one() == 0


def test_times_keep_their_time_zone_and_exact_instant(db_session):
    user = add_user(db_session)
    plus_five = timezone(timedelta(hours=5))
    local = datetime(2026, 3, 1, 13, 30, 15, 123456, tzinfo=plus_five)
    reading = GlucoseReading(user_id=user.id, glucose_value=Decimal("100"),
                             reading_type=ReadingType.FASTING, recorded_at=local)
    db_session.add(reading)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(GlucoseReading, reading.id).recorded_at
    assert stored.tzinfo is not None
    assert stored == local  # the same instant
    assert stored.astimezone(timezone.utc) == datetime(2026, 3, 1, 8, 30, 15, 123456, tzinfo=timezone.utc)


def test_decimal_values_are_exact(db_session):
    user = add_user(db_session)
    reading = GlucoseReading(user_id=user.id, glucose_value=Decimal("95.55"), reading_type=ReadingType.FASTING)
    db_session.add(reading)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(GlucoseReading, reading.id).glucose_value == Decimal("95.55")


# ---------------------------------------------------------------------------
# The engine settings used by the app
# ---------------------------------------------------------------------------


def test_the_app_engine_settings_work_against_postgresql():
    url = normalize_database_url(TEST_DATABASE_URL)
    engine = create_engine(url, **_engine_options(url))
    try:
        with engine.connect() as connection:
            for _ in range(12):  # psycopg would normally start preparing after 5
                assert connection.execute(text("SELECT 1")).scalar_one() == 1
            assert connection.connection.dbapi_connection.prepare_threshold is None
            prepared = connection.execute(text("SELECT COUNT(*) FROM pg_prepared_statements")).scalar_one()
            assert prepared == 0  # no server-side prepared statements (pooler safe)
        assert make_url(url).get_backend_name() == "postgresql"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# A whole user journey through the real API on PostgreSQL
# ---------------------------------------------------------------------------


def test_full_journey_signup_to_pdf_report(client):
    # Registration, login and the protected route.
    signup = client.post("/auth/signup", json={
        "full_name": "Journey Person", "email": "journey@example.com", "password": PASSWORD})
    assert signup.status_code == 201
    assert client.post("/auth/signup", json={
        "full_name": "Journey Person", "email": "journey@example.com", "password": PASSWORD}).status_code == 409
    assert client.post("/auth/login", json={"email": "journey@example.com", "password": "wrong-password"}).status_code == 401
    token = client.post("/auth/login", json={"email": "journey@example.com", "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me").status_code == 401  # logged out = no access
    assert client.get("/auth/me", headers=headers).json()["email"] == "journey@example.com"

    # Glucose and blood pressure: create, list, update, delete.
    when = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    glucose = client.post("/glucose", headers=headers, json={
        "glucose_value": 98.6, "reading_type": "fasting", "recorded_at": when, "notes": "fake"})
    assert glucose.status_code == 201
    glucose_id = glucose.json()["id"]
    pressure = client.post("/blood-pressure", headers=headers, json={
        "systolic": 121, "diastolic": 79, "pulse": 66, "recorded_at": when})
    assert pressure.status_code == 201
    pressure_id = pressure.json()["id"]
    assert len(client.get("/glucose", headers=headers).json()) == 1
    assert client.patch(f"/glucose/{glucose_id}", headers=headers, json={"glucose_value": 101.25}).status_code == 200
    assert client.patch(f"/blood-pressure/{pressure_id}", headers=headers, json={"systolic": 125}).status_code == 200
    assert float(client.get(f"/glucose/{glucose_id}", headers=headers).json()["glucose_value"]) == 101.25

    # Statistics, charts and the PDF report.
    now = datetime.now(timezone.utc)
    span = {"start": (now - timedelta(days=7)).isoformat(), "end": (now + timedelta(days=1)).isoformat()}
    stats = client.get("/stats/glucose", headers=headers, params=span).json()
    assert stats["count"] == 1 and float(stats["average"]) == 101.25
    assert len(client.get("/charts/glucose", headers=headers, params=span).json()["points"]) == 1
    assert len(client.get("/charts/blood-pressure", headers=headers, params=span).json()["points"]) == 1
    report = client.get("/reports/pdf", headers=headers, params=span)
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert report.content.startswith(b"%PDF")

    # Delete.
    assert client.delete(f"/glucose/{glucose_id}", headers=headers).status_code == 204
    assert client.delete(f"/blood-pressure/{pressure_id}", headers=headers).status_code == 204
    assert client.get("/glucose", headers=headers).json() == []

    # The deployment health check.
    assert client.get("/health/db").json() == {"status": "ready"}


def test_admin_features_work_on_postgresql(client, db_session):
    admin = add_user(db_session, "admin@example.com", role="admin")
    from app.core.security import hash_password
    admin.hashed_password = hash_password(PASSWORD)
    db_session.commit()
    token = client.post("/auth/login", json={"email": admin.email, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    other = add_user(db_session, "someone@example.com")

    overview = client.get("/admin/overview", headers=headers).json()
    assert overview["users"]["total"] == 2 and overview["users"]["admins"] == 1
    assert client.patch(f"/admin/users/{other.id}/role", headers=headers, json={"role": "admin"}).status_code == 200
    assert client.patch(f"/admin/users/{admin.id}/role", headers=headers, json={"role": "user"}).status_code == 409
    activity = client.get("/admin/activity", headers=headers).json()
    assert activity["total"] == 1 and activity["items"][0]["action"] == "admin_promoted"
    assert client.get("/admin/users?search=some", headers=headers).json()["total"] == 1

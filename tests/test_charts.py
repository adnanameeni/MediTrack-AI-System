from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.session import get_db
from app.dependencies import get_current_user
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User
from app.routes import charts

UTC = timezone.utc
START = datetime(2026, 3, 1, tzinfo=UTC)
END = datetime(2026, 3, 8, tzinfo=UTC)


class Env:
    """A private app, in-memory database and two fake users for these tests."""

    def __init__(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.alice = User(
            full_name="Alice Example", email="alice@example.com", hashed_password="x"
        )
        self.bob = User(
            full_name="Bob Example", email="bob@example.com", hashed_password="x"
        )
        self.db.add_all([self.alice, self.bob])
        self.db.commit()
        self.current_id = self.alice.id

        app = FastAPI()
        app.include_router(charts.router)

        def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        def override_user():
            session = self.Session()
            try:
                return session.get(User, self.current_id)
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(app)

    def glucose(self, user, when, value="100.00", kind=ReadingType.FASTING):
        self.db.add(
            GlucoseReading(
                user_id=user.id,
                glucose_value=Decimal(value),
                reading_type=kind,
                recorded_at=when,
            )
        )
        self.db.commit()

    def pressure(self, user, when, systolic=120, diastolic=80, pulse=None):
        self.db.add(
            BloodPressureReading(
                user_id=user.id,
                systolic=systolic,
                diastolic=diastolic,
                pulse=pulse,
                recorded_at=when,
            )
        )
        self.db.commit()

    def get(self, path, start=START, end=END):
        return self.client.get(
            path, params={"start": start.isoformat(), "end": end.isoformat()}
        )


@pytest.fixture
def env():
    return Env()


def test_glucose_points_are_in_range_and_oldest_first(env):
    env.glucose(env.alice, START + timedelta(days=2), "110.00")
    env.glucose(env.alice, START, "90.00")  # start is included
    env.glucose(env.alice, END, "150.00")  # end is excluded
    env.glucose(env.alice, START - timedelta(hours=1), "80.00")  # before the range

    response = env.get("/charts/glucose")

    assert response.status_code == 200
    body = response.json()
    assert [p["glucose_value"] for p in body["points"]] == [90.0, 110.0]
    assert body["truncated"] is False


def test_glucose_point_shape_and_timezone(env):
    env.glucose(env.alice, START + timedelta(hours=5), "101.50", ReadingType.AFTER_MEAL)

    point = env.get("/charts/glucose").json()["points"][0]

    assert set(point) == {"recorded_at", "glucose_value", "reading_type"}
    assert point["reading_type"] == "after_meal"
    assert point["glucose_value"] == 101.5
    assert point["recorded_at"].endswith(("Z", "+00:00"))


def test_blood_pressure_points(env):
    env.pressure(env.alice, START + timedelta(days=1), 130, 85, 72)
    env.pressure(env.alice, START + timedelta(days=2), 118, 76, None)

    body = env.get("/charts/blood-pressure").json()

    assert [(p["systolic"], p["diastolic"], p["pulse"]) for p in body["points"]] == [
        (130, 85, 72),
        (118, 76, None),
    ]
    assert set(body["points"][0]) == {"recorded_at", "systolic", "diastolic", "pulse"}


def test_users_only_get_their_own_points(env):
    env.glucose(env.alice, START + timedelta(days=1), "100.00")
    env.glucose(env.bob, START + timedelta(days=1), "222.00")
    env.pressure(env.bob, START + timedelta(days=1), 150, 95)

    alice_glucose = env.get("/charts/glucose").json()["points"]
    alice_pressure = env.get("/charts/blood-pressure").json()["points"]
    assert [p["glucose_value"] for p in alice_glucose] == [100.0]
    assert alice_pressure == []

    env.current_id = env.bob.id
    bob_glucose = env.get("/charts/glucose").json()["points"]
    bob_pressure = env.get("/charts/blood-pressure").json()["points"]
    assert [p["glucose_value"] for p in bob_glucose] == [222.0]
    assert len(bob_pressure) == 1


@pytest.mark.parametrize("path", ["/charts/glucose", "/charts/blood-pressure"])
def test_empty_range_returns_no_points(env, path):
    body = env.get(path).json()
    assert body == {"points": [], "truncated": False}


@pytest.mark.parametrize("path", ["/charts/glucose", "/charts/blood-pressure"])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, START),
        (END, START),
        (START, START + timedelta(days=367)),
    ],
)
def test_invalid_ranges_are_rejected(env, path, start, end):
    response = env.get(path, start, end)
    assert response.status_code == 422


def test_a_366_day_range_is_allowed(env):
    assert env.get("/charts/glucose", START, START + timedelta(days=366)).status_code == 200


@pytest.mark.parametrize("path", ["/charts/glucose", "/charts/blood-pressure"])
def test_missing_dates_are_rejected(env, path):
    assert env.client.get(path).status_code == 422
    assert env.client.get(path, params={"start": START.isoformat()}).status_code == 422


def test_dates_without_a_time_zone_are_treated_as_utc(env):
    env.glucose(env.alice, START + timedelta(hours=1), "100.00")
    response = env.client.get(
        "/charts/glucose",
        params={"start": "2026-03-01T00:00:00", "end": "2026-03-02T00:00:00"},
    )
    assert response.status_code == 200
    assert len(response.json()["points"]) == 1


def test_results_are_capped_and_flagged(env, monkeypatch):
    monkeypatch.setattr(charts, "MAX_POINTS", 2)
    for day, value in enumerate(["91.00", "92.00", "93.00"], start=1):
        env.glucose(env.alice, START + timedelta(days=day), value)

    body = env.get("/charts/glucose").json()

    assert body["truncated"] is True
    assert [p["glucose_value"] for p in body["points"]] == [92.0, 93.0]


@pytest.mark.parametrize("path", ["/charts/glucose", "/charts/blood-pressure"])
def test_chart_endpoints_require_login(path):
    from main import app

    response = TestClient(app).get(
        path, params={"start": START.isoformat(), "end": END.isoformat()}
    )
    assert response.status_code in (401, 403)
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.session import get_db
from app.dependencies import get_current_user
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User
from app.reporting import pdf_report
from app.reporting.pdf_report import GlucoseRow, PressureRow, build_report_pdf
from app.routes import reports

UTC = timezone.utc
START = datetime(2026, 3, 1, tzinfo=UTC)
END = datetime(2026, 3, 8, tzinfo=UTC)


def pdf_text(pdf: bytes) -> str:
    """Readable text from a PDF built with compress=False and useA85 turned off."""
    return b"\n".join(re.findall(rb"\((.*?)\) Tj", pdf)).decode("latin-1")


@pytest.fixture
def readable_pdf(monkeypatch):
    monkeypatch.setattr(rl_config, "useA85", 0)


def make_builder_args(**overrides):
    args = dict(
        full_name="Alice Example",
        start=START,
        end=END,
        glucose=[],
        pressure=[],
        offset_minutes=0,
        generated_at=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
        compress=False,
    )
    args.update(overrides)
    return args


# ---------------------------------------------------------------------------
# The PDF builder on its own
# ---------------------------------------------------------------------------


def test_pdf_is_a_real_pdf_with_title_name_and_disclaimer(readable_pdf):
    pdf = build_report_pdf(**make_builder_args())
    text = pdf_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-20:]
    assert "MediTrack AI Health Report" in text
    assert "Prepared for: Alice Example" in text
    assert "No glucose readings in this period." in text
    assert "No blood pressure readings in this period." in text
    assert "not medical advice" in text.lower() or "Not medical advice" in text


def test_pdf_shows_statistics_and_readings(readable_pdf):
    glucose = [
        GlucoseRow(START + timedelta(days=1), 100.0, "fasting", None),
        GlucoseRow(START + timedelta(days=2), 130.5, "after_meal", "Example note"),
    ]
    pressure = [
        PressureRow(START + timedelta(days=1), 120, 80, 70, None),
        PressureRow(START + timedelta(days=2), 130, 90, None, None),
    ]

    text = pdf_text(build_report_pdf(**make_builder_args(glucose=glucose, pressure=pressure)))

    assert "115.25" in text  # average glucose
    assert "100" in text and "130.5" in text
    assert "After meal" in text
    assert "Example note" in text
    assert "125/85" in text  # average blood pressure
    assert "120-130" in text  # systolic range
    assert "80-90" in text  # diastolic range
    assert "70" in text  # average pulse (only one pulse recorded)


def test_times_are_shown_in_the_requested_offset(readable_pdf):
    glucose = [GlucoseRow(datetime(2026, 3, 2, 8, 0, tzinfo=UTC), 100.0, "fasting", None)]

    text = pdf_text(
        build_report_pdf(**make_builder_args(glucose=glucose, offset_minutes=300))
    )

    assert "UTC+05:00" in text
    assert "2026-03-02 13:00" in text


def test_negative_offset_label(readable_pdf):
    text = pdf_text(build_report_pdf(**make_builder_args(offset_minutes=-210)))
    assert "UTC-03:30" in text


def test_notes_with_markup_and_unicode_do_not_break_the_pdf():
    glucose = [
        GlucoseRow(START + timedelta(days=1), 100.0, "fasting", "<b>bold</b> & <i>oops"),
        GlucoseRow(START + timedelta(days=2), 101.0, "fasting", "نوٹ 😀 <para>"),
    ]
    pdf = build_report_pdf(
        **make_builder_args(full_name="Ünïcode <Name> & Co", glucose=glucose)
    )
    assert pdf.startswith(b"%PDF-")


def test_long_reports_use_several_pages():
    glucose = [
        GlucoseRow(START + timedelta(minutes=i), 100.0 + (i % 5), "fasting", "n")
        for i in range(400)
    ]
    pdf = build_report_pdf(**make_builder_args(glucose=glucose))
    assert len(re.findall(rb"/Type /Page\b", pdf)) > 1


def test_table_is_capped_but_statistics_use_every_reading(readable_pdf, monkeypatch):
    monkeypatch.setattr(pdf_report, "MAX_TABLE_ROWS", 2)
    glucose = [
        GlucoseRow(START + timedelta(days=i), float(value), "fasting", None)
        for i, value in enumerate([90, 100, 110, 120], start=1)
    ]

    text = pdf_text(build_report_pdf(**make_builder_args(glucose=glucose)))

    assert "most recent 2 of 4" in text
    assert "105" in text  # average of all four readings


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


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
        app.include_router(reports.router)

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

    def glucose(self, user, when, value="100.00", notes=None):
        self.db.add(
            GlucoseReading(
                user_id=user.id,
                glucose_value=Decimal(value),
                reading_type=ReadingType.FASTING,
                recorded_at=when,
                notes=notes,
            )
        )
        self.db.commit()

    def pressure(self, user, when, systolic=120, diastolic=80):
        self.db.add(
            BloodPressureReading(
                user_id=user.id,
                systolic=systolic,
                diastolic=diastolic,
                recorded_at=when,
            )
        )
        self.db.commit()

    def get(self, start=START, end=END, **extra):
        params = {"start": start.isoformat(), "end": end.isoformat()}
        params.update(extra)
        return self.client.get("/reports/pdf", params=params)


@pytest.fixture
def env():
    return Env()


def test_endpoint_returns_a_pdf_that_is_not_cached(env):
    env.glucose(env.alice, START + timedelta(days=1))

    response = env.get()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert "alice" not in response.headers["content-disposition"].lower()
    assert response.content.startswith(b"%PDF-")


def test_report_contains_only_the_logged_in_users_readings_in_range(env, monkeypatch):
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return b"%PDF-fake"

    monkeypatch.setattr(reports, "build_report_pdf", fake_builder)

    env.glucose(env.alice, START + timedelta(days=1), "100.00")
    env.glucose(env.alice, START, "90.00")  # start is included
    env.glucose(env.alice, END, "150.00")  # end is excluded
    env.glucose(env.alice, START - timedelta(hours=1), "80.00")  # before the range
    env.glucose(env.bob, START + timedelta(days=1), "222.00")  # someone else's
    env.pressure(env.alice, START + timedelta(days=1), 118, 76)
    env.pressure(env.bob, START + timedelta(days=1), 150, 95)

    response = env.get(offset_minutes=300)

    assert response.status_code == 200
    assert captured["full_name"] == "Alice Example"
    assert [r.value for r in captured["glucose"]] == [90.0, 100.0]
    assert [(r.systolic, r.diastolic) for r in captured["pressure"]] == [(118, 76)]
    assert captured["offset_minutes"] == 300

    env.current_id = env.bob.id
    env.get()
    assert captured["full_name"] == "Bob Example"
    assert [r.value for r in captured["glucose"]] == [222.0]
    assert [(r.systolic, r.diastolic) for r in captured["pressure"]] == [(150, 95)]


def test_endpoint_works_with_no_readings(env):
    response = env.get()
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, START),
        (END, START),
        (START, START + timedelta(days=367)),
    ],
)
def test_invalid_ranges_are_rejected(env, start, end):
    assert env.get(start, end).status_code == 422


def test_a_366_day_range_is_allowed(env):
    assert env.get(START, START + timedelta(days=366)).status_code == 200


def test_missing_dates_are_rejected(env):
    assert env.client.get("/reports/pdf").status_code == 422
    assert env.client.get("/reports/pdf", params={"start": START.isoformat()}).status_code == 422


@pytest.mark.parametrize("offset", [841, -841, "abc"])
def test_offset_must_be_reasonable(env, offset):
    assert env.get(offset_minutes=offset).status_code == 422


def test_report_endpoint_requires_login():
    from main import app

    response = TestClient(app).get(
        "/reports/pdf",
        params={"start": START.isoformat(), "end": END.isoformat()},
    )
    assert response.status_code in (401, 403)
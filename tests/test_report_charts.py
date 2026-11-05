import re
from datetime import datetime, timedelta, timezone

import pytest
from reportlab import rl_config

from app.reporting.pdf_report import GlucoseRow, PressureRow, build_report_pdf

UTC = timezone.utc
START = datetime(2026, 3, 1, tzinfo=UTC)
END = datetime(2026, 3, 8, tzinfo=UTC)


def pdf_text(pdf: bytes) -> str:
    """Readable text from a PDF built with compress=False and useA85 turned off."""
    return b"\n".join(re.findall(rb"\((.*?)\) Tj", pdf)).decode("latin-1")


@pytest.fixture
def readable_pdf(monkeypatch):
    monkeypatch.setattr(rl_config, "useA85", 0)


def build(**overrides) -> bytes:
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
    return build_report_pdf(**args)


def test_both_charts_and_all_existing_sections_are_present(readable_pdf):
    glucose = [
        GlucoseRow(START + timedelta(days=1), 100.0, "fasting", None),
        GlucoseRow(START + timedelta(days=3), 130.5, "after_meal", "Example note"),
    ]
    pressure = [
        PressureRow(START + timedelta(days=1), 120, 80, 70, None),
        PressureRow(START + timedelta(days=3), 130, 90, None, None),
    ]

    pdf = build(glucose=glucose, pressure=pressure, offset_minutes=300)
    text = pdf_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert "Blood glucose over time" in text
    assert "Blood pressure over time" in text
    assert "Systolic" in text and "Diastolic" in text
    assert "01 Mar" in text  # first label of the time axis
    # Everything that was already in the report is still there.
    assert "MediTrack AI Health Report" in text
    assert "Prepared for: Alice Example" in text
    # At UTC+05:00 the last second of the period falls on 8 March.
    assert "Period: 2026-03-01 to 2026-03-08" in text
    assert "UTC+05:00" in text
    assert "115.25" in text
    assert "125/85" in text
    assert "Date and time" in text
    assert "Example note" in text
    assert "not medical advice" in text.lower()


def test_no_charts_when_there_are_no_readings(readable_pdf):
    text = pdf_text(build())

    assert "over time" not in text
    assert "No glucose readings in this period." in text
    assert "No blood pressure readings in this period." in text


def test_only_the_chart_with_data_is_drawn(readable_pdf):
    glucose = [GlucoseRow(START + timedelta(days=2), 99.0, "fasting", None)]

    text = pdf_text(build(glucose=glucose))

    assert "Blood glucose over time" in text
    assert "Blood pressure over time" not in text


def test_single_reading_and_constant_values_do_not_break_the_charts(readable_pdf):
    glucose = [GlucoseRow(START + timedelta(hours=5), 100.0, "fasting", None)]
    pressure = [
        PressureRow(START + timedelta(hours=5), 120, 80, None, None),
        PressureRow(START + timedelta(hours=6), 120, 80, None, None),
    ]

    pdf = build(glucose=glucose, pressure=pressure, end=START + timedelta(hours=12))
    text = pdf_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert "Blood glucose over time" in text
    assert "Blood pressure over time" in text


def test_large_reports_still_build_with_charts(readable_pdf):
    glucose = [
        GlucoseRow(START + timedelta(minutes=10 * i), 90.0 + (i % 40), "fasting", "n")
        for i in range(500)
    ]
    pressure = [
        PressureRow(START + timedelta(minutes=10 * i), 110 + (i % 30), 70 + (i % 15), 65, "n")
        for i in range(500)
    ]

    pdf = build(glucose=glucose, pressure=pressure)
    text = pdf_text(pdf)

    assert pdf.startswith(b"%PDF-")
    assert "Blood glucose over time" in text
    assert "Blood pressure over time" in text
    assert len(re.findall(rb"/Type /Page\b", pdf)) > 1
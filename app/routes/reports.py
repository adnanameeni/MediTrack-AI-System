from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies import get_current_user
from app.models import BloodPressureReading, GlucoseReading, User
from app.reporting.pdf_report import GlucoseRow, PressureRow, build_report_pdf

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_RANGE_DAYS = 366


def _as_utc(value: datetime) -> datetime:
    # SQLite returns datetimes without time zone information; they are UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _checked_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if end_utc <= start_utc or end_utc - start_utc > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=422,
            detail="The date range must be positive and at most 366 days.",
        )
    return start_utc, end_utc


@router.get("/pdf")
def pdf_report(
    start: datetime = Query(...),
    end: datetime = Query(...),
    offset_minutes: int = Query(0, ge=-840, le=840),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """A PDF with the logged-in user's own readings. Start included, end excluded."""
    start_utc, end_utc = _checked_range(start, end)

    glucose = [
        GlucoseRow(
            recorded_at=_as_utc(r.recorded_at),
            value=float(r.glucose_value),
            reading_type=getattr(r.reading_type, "value", r.reading_type),
            notes=r.notes,
        )
        for r in db.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.user_id == current_user.id)
            .order_by(GlucoseReading.recorded_at, GlucoseReading.id)
        ).all()
        if start_utc <= _as_utc(r.recorded_at) < end_utc
    ]
    pressure = [
        PressureRow(
            recorded_at=_as_utc(r.recorded_at),
            systolic=r.systolic,
            diastolic=r.diastolic,
            pulse=r.pulse,
            notes=r.notes,
        )
        for r in db.scalars(
            select(BloodPressureReading)
            .where(BloodPressureReading.user_id == current_user.id)
            .order_by(BloodPressureReading.recorded_at, BloodPressureReading.id)
        ).all()
        if start_utc <= _as_utc(r.recorded_at) < end_utc
    ]

    pdf = build_report_pdf(
        full_name=current_user.full_name,
        start=start_utc,
        end=end_utc,
        glucose=glucose,
        pressure=pressure,
        offset_minutes=offset_minutes,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="meditrack-report.pdf"',
            "Cache-Control": "no-store",
        },
    )
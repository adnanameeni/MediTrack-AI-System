from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies import get_current_user
from app.models import BloodPressureReading, GlucoseReading, User
from app.schemas.chart import (
    BloodPressureChartData,
    BloodPressureChartPoint,
    GlucoseChartData,
    GlucoseChartPoint,
)

router = APIRouter(prefix="/charts", tags=["charts"])

MAX_RANGE_DAYS = 366
MAX_POINTS = 2000


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


def _in_range(readings, start: datetime, end: datetime) -> tuple[list, bool]:
    """Keep readings with start <= time < end, oldest first, capped at MAX_POINTS."""
    chosen = [r for r in readings if start <= _as_utc(r.recorded_at) < end]
    truncated = len(chosen) > MAX_POINTS
    if truncated:
        chosen = chosen[-MAX_POINTS:]
    return chosen, truncated


@router.get("/glucose", response_model=GlucoseChartData)
def glucose_chart(
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GlucoseChartData:
    start_utc, end_utc = _checked_range(start, end)
    readings = db.scalars(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == current_user.id)
        .order_by(GlucoseReading.recorded_at, GlucoseReading.id)
    ).all()
    chosen, truncated = _in_range(readings, start_utc, end_utc)
    points = [
        GlucoseChartPoint(
            recorded_at=_as_utc(r.recorded_at),
            glucose_value=float(r.glucose_value),
            reading_type=getattr(r.reading_type, "value", r.reading_type),
        )
        for r in chosen
    ]
    return GlucoseChartData(points=points, truncated=truncated)


@router.get("/blood-pressure", response_model=BloodPressureChartData)
def blood_pressure_chart(
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BloodPressureChartData:
    start_utc, end_utc = _checked_range(start, end)
    readings = db.scalars(
        select(BloodPressureReading)
        .where(BloodPressureReading.user_id == current_user.id)
        .order_by(BloodPressureReading.recorded_at, BloodPressureReading.id)
    ).all()
    chosen, truncated = _in_range(readings, start_utc, end_utc)
    points = [
        BloodPressureChartPoint(
            recorded_at=_as_utc(r.recorded_at),
            systolic=r.systolic,
            diastolic=r.diastolic,
            pulse=r.pulse,
        )
        for r in chosen
    ]
    return BloodPressureChartData(points=points, truncated=truncated)
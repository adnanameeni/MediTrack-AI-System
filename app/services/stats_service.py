from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BloodPressureReading, GlucoseReading
from app.schemas.stats import BloodPressureStats, GlucoseStats, as_utc

TWO_PLACES = Decimal("0.01")


def _average(values: list) -> Decimal | None:
    if not values:
        return None
    total = sum((Decimal(str(value)) for value in values), Decimal("0"))
    return (total / len(values)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _in_range(rows, start: datetime, end: datetime):
    """Keep rows whose time falls in [start, end). Naive times are UTC."""
    return [row for row in rows if start <= as_utc(row.recorded_at) < end]


def glucose_stats(
    db: Session, user_id: int, start: datetime, end: datetime
) -> GlucoseStats:
    start, end = as_utc(start), as_utc(end)
    rows = db.scalars(
        select(GlucoseReading).where(GlucoseReading.user_id == user_id)
    ).all()
    values = [Decimal(str(row.glucose_value)) for row in _in_range(rows, start, end)]
    return GlucoseStats(
        start=start,
        end=end,
        count=len(values),
        average=_average(values),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
    )


def blood_pressure_stats(
    db: Session, user_id: int, start: datetime, end: datetime
) -> BloodPressureStats:
    start, end = as_utc(start), as_utc(end)
    rows = db.scalars(
        select(BloodPressureReading).where(BloodPressureReading.user_id == user_id)
    ).all()
    rows = _in_range(rows, start, end)
    systolic = [row.systolic for row in rows]
    diastolic = [row.diastolic for row in rows]
    pulse = [row.pulse for row in rows if row.pulse is not None]
    return BloodPressureStats(
        start=start,
        end=end,
        count=len(rows),
        average_systolic=_average(systolic),
        average_diastolic=_average(diastolic),
        average_pulse=_average(pulse),
        minimum_systolic=min(systolic) if systolic else None,
        maximum_systolic=max(systolic) if systolic else None,
        minimum_diastolic=min(diastolic) if diastolic else None,
        maximum_diastolic=max(diastolic) if diastolic else None,
    )
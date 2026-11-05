from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel

MAX_RANGE = timedelta(days=366)


def as_utc(value: datetime) -> datetime:
    """Treat a time without a time zone as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class GlucoseStats(BaseModel):
    start: datetime
    end: datetime
    count: int
    average: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


class BloodPressureStats(BaseModel):
    start: datetime
    end: datetime
    count: int
    average_systolic: Decimal | None
    average_diastolic: Decimal | None
    average_pulse: Decimal | None
    minimum_systolic: int | None
    maximum_systolic: int | None
    minimum_diastolic: int | None
    maximum_diastolic: int | None
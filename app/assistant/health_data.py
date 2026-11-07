"""Facts about one user's own readings: periods, summaries, extremes, trends, comparisons.

The language model never queries the database. It only receives what this module computes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BloodPressureReading, GlucoseReading

PERIODS = (
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "all_time",
)
METRICS = ("glucose", "blood_pressure", "both")

PERIOD_LABELS = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7_days": "the last 7 days",
    "last_30_days": "the last 30 days",
    "this_week": "this week (Monday to Sunday)",
    "last_week": "last week (Monday to Sunday)",
    "this_month": "this month",
    "last_month": "last month",
    "all_time": "all recorded time",
}

MIN_TREND_READINGS = 4  # fewer readings than this: no trend is reported
TREND_TOLERANCE = 0.03  # changes within 3% of the earlier average count as "about the same"


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start_utc: datetime
    end_utc: datetime  # excluded
    offset_minutes: int

    def _local(self, value: datetime) -> datetime:
        return value + timedelta(minutes=self.offset_minutes)

    @property
    def first_day(self) -> str | None:
        if self.key == "all_time":
            return None
        return self._local(self.start_utc).strftime("%Y-%m-%d")

    @property
    def last_day(self) -> str:
        return self._local(self.end_utc - timedelta(seconds=1)).strftime("%Y-%m-%d")


def resolve_period(
    period: str, offset_minutes: int = 0, now: datetime | None = None
) -> Period:
    """Turn a period name into exact UTC start and end times (start included, end excluded)."""
    if period not in PERIODS:
        raise ValueError(f"Unknown period: {period}")

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_now = now_utc.replace(tzinfo=None) + timedelta(minutes=offset_minutes)

    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    ranges = {
        "today": (today, tomorrow),
        "yesterday": (today - timedelta(days=1), today),
        "last_7_days": (tomorrow - timedelta(days=7), tomorrow),
        "last_30_days": (tomorrow - timedelta(days=30), tomorrow),
        "this_week": (week_start, week_start + timedelta(days=7)),
        "last_week": (week_start - timedelta(days=7), week_start),
        "this_month": (month_start, next_month),
        "last_month": (last_month_start, month_start),
        "all_time": (datetime(2000, 1, 1), tomorrow),
    }
    local_start, local_end = ranges[period]

    def to_utc(local: datetime) -> datetime:
        return (local - timedelta(minutes=offset_minutes)).replace(tzinfo=timezone.utc)

    return Period(
        key=period,
        label=PERIOD_LABELS[period],
        start_utc=to_utc(local_start),
        end_utc=to_utc(local_end),
        offset_minutes=offset_minutes,
    )


# ---------------------------------------------------------------------------
# Loading (every query is filtered by the given user id)
# ---------------------------------------------------------------------------


def _as_utc(value: datetime) -> datetime:
    # SQLite returns datetimes without time zone information; they are UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _in_period(rows, period: Period) -> list:
    return [r for r in rows if period.start_utc <= _as_utc(r.recorded_at) < period.end_utc]


def load_glucose(db: Session, user_id: int, period: Period) -> list[GlucoseReading]:
    rows = db.scalars(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(GlucoseReading.recorded_at, GlucoseReading.id)
    ).all()
    return _in_period(rows, period)


def load_pressure(db: Session, user_id: int, period: Period) -> list[BloodPressureReading]:
    rows = db.scalars(
        select(BloodPressureReading)
        .where(BloodPressureReading.user_id == user_id)
        .order_by(BloodPressureReading.recorded_at, BloodPressureReading.id)
    ).all()
    return _in_period(rows, period)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _num(value: float) -> float:
    return round(float(value), 2)


def _local_text(value: datetime, offset_minutes: int) -> str:
    local = _as_utc(value) + timedelta(minutes=offset_minutes)
    return local.strftime("%Y-%m-%d %H:%M")


def _trend(values: list[float]) -> dict | None:
    """Compare the earlier half of the readings with the later half."""
    if len(values) < MIN_TREND_READINGS:
        return None
    half = len(values) // 2
    first = sum(values[:half]) / half
    second = sum(values[-half:]) / half
    change = second - first
    if abs(change) <= TREND_TOLERANCE * abs(first):
        direction = "about the same"
    elif change > 0:
        direction = "higher"
    else:
        direction = "lower"
    return {
        "readings_in_each_half": half,
        "earlier_half_average": _num(first),
        "later_half_average": _num(second),
        "change": _num(change),
        "later_compared_with_earlier": direction,
    }


def summarise_glucose(rows: list[GlucoseReading], offset_minutes: int = 0) -> dict | None:
    if not rows:
        return None
    values = [float(r.glucose_value) for r in rows]
    lowest = min(rows, key=lambda r: float(r.glucose_value))
    highest = max(rows, key=lambda r: float(r.glucose_value))

    by_type: dict[str, list[float]] = {}
    for row in rows:
        kind = getattr(row.reading_type, "value", row.reading_type)
        by_type.setdefault(kind, []).append(float(row.glucose_value))

    return {
        "count": len(rows),
        "average": _num(sum(values) / len(values)),
        "lowest": {
            "value": _num(lowest.glucose_value),
            "recorded_at": _local_text(lowest.recorded_at, offset_minutes),
        },
        "highest": {
            "value": _num(highest.glucose_value),
            "recorded_at": _local_text(highest.recorded_at, offset_minutes),
        },
        "by_reading_type": {
            kind: {"count": len(vals), "average": _num(sum(vals) / len(vals))}
            for kind, vals in by_type.items()
        },
        "trend": _trend(values),
    }


def summarise_pressure(
    rows: list[BloodPressureReading], offset_minutes: int = 0
) -> dict | None:
    if not rows:
        return None
    systolic = [float(r.systolic) for r in rows]
    diastolic = [float(r.diastolic) for r in rows]
    pulses = [float(r.pulse) for r in rows if r.pulse is not None]

    lowest = min(rows, key=lambda r: (r.systolic, r.diastolic))
    highest = max(rows, key=lambda r: (r.systolic, r.diastolic))

    return {
        "count": len(rows),
        "average_systolic": _num(sum(systolic) / len(rows)),
        "average_diastolic": _num(sum(diastolic) / len(rows)),
        "average_pulse": _num(sum(pulses) / len(pulses)) if pulses else None,
        "lowest": {
            "systolic": lowest.systolic,
            "diastolic": lowest.diastolic,
            "recorded_at": _local_text(lowest.recorded_at, offset_minutes),
        },
        "highest": {
            "systolic": highest.systolic,
            "diastolic": highest.diastolic,
            "recorded_at": _local_text(highest.recorded_at, offset_minutes),
        },
        "trend_systolic": _trend(systolic),
        "trend_diastolic": _trend(diastolic),
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def collect_facts(
    db: Session,
    user_id: int,
    metric: str,
    period_key: str,
    offset_minutes: int = 0,
    now: datetime | None = None,
) -> dict:
    """The facts for one metric and one period, for this user only."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    period = resolve_period(period_key, offset_minutes, now)

    glucose = None
    pressure = None
    if metric in ("glucose", "both"):
        glucose = summarise_glucose(load_glucose(db, user_id, period), offset_minutes)
    if metric in ("blood_pressure", "both"):
        pressure = summarise_pressure(load_pressure(db, user_id, period), offset_minutes)

    return {
        "metric": metric,
        "period": {
            "key": period.key,
            "label": period.label,
            "first_day": period.first_day,
            "last_day": period.last_day,
        },
        "glucose": glucose,
        "blood_pressure": pressure,
    }


def has_data(facts: dict) -> bool:
    return facts["glucose"] is not None or facts["blood_pressure"] is not None


def _difference(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return _num(current - previous)


def compare_facts(current: dict, previous: dict) -> dict:
    """Differences between two periods (current minus previous). None when either side has no data."""
    glucose_now = current["glucose"] or {}
    glucose_before = previous["glucose"] or {}
    pressure_now = current["blood_pressure"] or {}
    pressure_before = previous["blood_pressure"] or {}

    return {
        "current_period": current["period"]["label"],
        "previous_period": previous["period"]["label"],
        "glucose_average_change": _difference(
            glucose_now.get("average"), glucose_before.get("average")
        ),
        "systolic_average_change": _difference(
            pressure_now.get("average_systolic"), pressure_before.get("average_systolic")
        ),
        "diastolic_average_change": _difference(
            pressure_now.get("average_diastolic"), pressure_before.get("average_diastolic")
        ),
    }
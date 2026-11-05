from datetime import datetime

from pydantic import BaseModel


class GlucoseChartPoint(BaseModel):
    recorded_at: datetime
    glucose_value: float
    reading_type: str


class GlucoseChartData(BaseModel):
    points: list[GlucoseChartPoint]
    truncated: bool


class BloodPressureChartPoint(BaseModel):
    recorded_at: datetime
    systolic: int
    diastolic: int
    pulse: int | None


class BloodPressureChartData(BaseModel):
    points: list[BloodPressureChartPoint]
    truncated: bool
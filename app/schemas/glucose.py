from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ReadingType

MAX_NOTES_LENGTH = 500
FUTURE_TOLERANCE = timedelta(minutes=5)

GlucoseValue = Annotated[
    Decimal, Field(gt=0, le=1000, max_digits=6, decimal_places=2)
]


def _as_utc(value: datetime) -> datetime:
    """Treat a time without a time zone as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _check_not_in_future(value: datetime) -> datetime:
    value = _as_utc(value)
    if value > datetime.now(timezone.utc) + FUTURE_TOLERANCE:
        raise ValueError("recorded_at cannot be in the future")
    return value


class GlucoseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    glucose_value: GlucoseValue
    reading_type: ReadingType
    recorded_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at_ok(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _check_not_in_future(value)

    @field_validator("notes")
    @classmethod
    def _empty_notes_become_none(cls, value: str | None) -> str | None:
        return value or None


class GlucoseUpdate(BaseModel):
    """Only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    glucose_value: GlucoseValue | None = None
    reading_type: ReadingType | None = None
    recorded_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at_ok(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _check_not_in_future(value)

    @field_validator("notes")
    @classmethod
    def _empty_notes_become_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _check_fields(self) -> "GlucoseUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change")
        for name in ("glucose_value", "reading_type", "recorded_at"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class GlucoseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    glucose_value: Decimal
    reading_type: ReadingType
    recorded_at: datetime
    notes: str | None

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value)
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_NOTES_LENGTH = 500
FUTURE_TOLERANCE = timedelta(minutes=5)


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


class BloodPressureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    systolic: int = Field(ge=1, le=300)
    diastolic: int = Field(ge=1, le=300)
    pulse: int | None = Field(default=None, ge=1, le=300)
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
    def _systolic_above_diastolic(self) -> "BloodPressureCreate":
        if self.systolic <= self.diastolic:
            raise ValueError("systolic must be greater than diastolic")
        return self


class BloodPressureUpdate(BaseModel):
    """Only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    systolic: int | None = Field(default=None, ge=1, le=300)
    diastolic: int | None = Field(default=None, ge=1, le=300)
    pulse: int | None = Field(default=None, ge=1, le=300)
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
    def _check_fields(self) -> "BloodPressureUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change")
        for name in ("systolic", "diastolic", "recorded_at"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        if (
            self.systolic is not None
            and self.diastolic is not None
            and self.systolic <= self.diastolic
        ):
            raise ValueError("systolic must be greater than diastolic")
        return self


class BloodPressureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    systolic: int
    diastolic: int
    pulse: int | None
    recorded_at: datetime
    notes: str | None

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value)
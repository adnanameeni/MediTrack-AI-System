from datetime import date as Date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from app.schemas.stats import as_utc

Role = Literal["user", "admin"]

# Every response below lists its fields explicitly. There is no password, no
# password hash, no token and no health-record content anywhere in this file.


class _UtcTimes(BaseModel):
    """Makes every datetime in a response a UTC time with a time zone."""

    @field_validator("*", mode="after")
    @classmethod
    def _utc(cls, value):
        return as_utc(value) if isinstance(value, datetime) else value


# ---------------------------------------------------------------------------
# Admin profile
# ---------------------------------------------------------------------------


class AdminProfile(_UtcTimes):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class UserTotals(BaseModel):
    total: int
    admins: int
    normal_users: int
    active: int
    inactive: int
    active_admins: int


class RecordTotals(BaseModel):
    """Counts only. Never the readings or the conversation text itself."""

    glucose_readings: int
    blood_pressure_readings: int
    conversations: int


class RecentRegistrations(_UtcTimes):
    last_24_hours: int
    last_7_days: int
    last_30_days: int
    latest_registration_at: datetime | None


class TrendPoint(BaseModel):
    date: Date
    count: int


class RegistrationTrend(BaseModel):
    days: int
    total: int
    points: list[TrendPoint]


class AdminOverview(_UtcTimes):
    generated_at: datetime
    users: UserTotals
    records: RecordTotals
    recent_registrations: RecentRegistrations
    registration_trend: RegistrationTrend


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


class AdminUserRead(_UtcTimes):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime


class AdminUserDetail(AdminUserRead):
    # Counts only, so an administrator can see how much a person uses the
    # app without being able to read any of their health information.
    glucose_reading_count: int
    blood_pressure_reading_count: int
    conversation_count: int


class AdminUserPage(BaseModel):
    items: list[AdminUserRead]
    total: int
    limit: int
    offset: int


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


class AuditPerson(BaseModel):
    id: int
    full_name: str
    email: str


class AuditEntryRead(_UtcTimes):
    id: int
    action: str
    detail: str | None
    created_at: datetime
    # None means "the command line" for the administrator, and "a deleted
    # account" for the target.
    admin: AuditPerson | None
    target: AuditPerson | None


class AuditPage(BaseModel):
    items: list[AuditEntryRead]
    total: int
    limit: int
    offset: int

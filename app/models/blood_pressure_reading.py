from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BloodPressureReading(Base):
    __tablename__ = "blood_pressure_readings"
    __table_args__ = (
        CheckConstraint("systolic > 0", name="ck_blood_pressure_readings_systolic_positive"),
        CheckConstraint("diastolic > 0", name="ck_blood_pressure_readings_diastolic_positive"),
        CheckConstraint(
            "systolic > diastolic",
            name="ck_blood_pressure_readings_systolic_gt_diastolic",
        ),
        CheckConstraint(
            "pulse IS NULL OR pulse > 0",
            name="ck_blood_pressure_readings_pulse_positive",
        ),
        Index("ix_blood_pressure_readings_user_id_recorded_at", "user_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    systolic: Mapped[int] = mapped_column(Integer, nullable=False)
    diastolic: Mapped[int] = mapped_column(Integer, nullable=False)
    pulse: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="blood_pressure_readings")
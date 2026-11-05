import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ReadingType(str, enum.Enum):
    FASTING = "fasting"
    BEFORE_MEAL = "before_meal"
    AFTER_MEAL = "after_meal"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GlucoseReading(Base):
    __tablename__ = "glucose_readings"
    __table_args__ = (
        CheckConstraint(
            "glucose_value > 0",
            name="ck_glucose_readings_glucose_value_positive",
        ),
        Index("ix_glucose_readings_user_id_recorded_at", "user_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    glucose_value: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    reading_type: Mapped[ReadingType] = mapped_column(
        Enum(
            ReadingType,
            name="glucose_reading_type",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="glucose_readings")
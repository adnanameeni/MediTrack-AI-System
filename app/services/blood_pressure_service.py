from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BloodPressureReading
from app.schemas.blood_pressure import BloodPressureCreate, BloodPressureUpdate


class InvalidPressurePairError(ValueError):
    """Systolic would not be greater than diastolic after the change."""


def create_reading(
    db: Session, user_id: int, data: BloodPressureCreate
) -> BloodPressureReading:
    reading = BloodPressureReading(
        user_id=user_id,
        systolic=data.systolic,
        diastolic=data.diastolic,
        pulse=data.pulse,
        notes=data.notes,
    )
    if data.recorded_at is not None:
        reading.recorded_at = data.recorded_at
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


def list_readings(
    db: Session, user_id: int, limit: int = 50, offset: int = 0
) -> list[BloodPressureReading]:
    statement = (
        select(BloodPressureReading)
        .where(BloodPressureReading.user_id == user_id)
        .order_by(
            BloodPressureReading.recorded_at.desc(), BloodPressureReading.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))


def get_reading(
    db: Session, user_id: int, reading_id: int
) -> BloodPressureReading | None:
    """Return the reading only if it belongs to this user."""
    statement = select(BloodPressureReading).where(
        BloodPressureReading.id == reading_id,
        BloodPressureReading.user_id == user_id,
    )
    return db.scalar(statement)


def update_reading(
    db: Session, reading: BloodPressureReading, data: BloodPressureUpdate
) -> BloodPressureReading:
    changes = data.model_dump(exclude_unset=True)
    new_systolic = changes.get("systolic", reading.systolic)
    new_diastolic = changes.get("diastolic", reading.diastolic)
    if new_systolic <= new_diastolic:
        raise InvalidPressurePairError()

    for field, value in changes.items():
        setattr(reading, field, value)
    db.commit()
    db.refresh(reading)
    return reading


def delete_reading(db: Session, reading: BloodPressureReading) -> None:
    db.delete(reading)
    db.commit()
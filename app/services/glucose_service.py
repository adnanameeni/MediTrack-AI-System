from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GlucoseReading
from app.schemas.glucose import GlucoseCreate, GlucoseUpdate


def create_reading(db: Session, user_id: int, data: GlucoseCreate) -> GlucoseReading:
    reading = GlucoseReading(
        user_id=user_id,
        glucose_value=data.glucose_value,
        reading_type=data.reading_type,
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
) -> list[GlucoseReading]:
    statement = (
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(GlucoseReading.recorded_at.desc(), GlucoseReading.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))


def get_reading(db: Session, user_id: int, reading_id: int) -> GlucoseReading | None:
    """Return the reading only if it belongs to this user."""
    statement = select(GlucoseReading).where(
        GlucoseReading.id == reading_id,
        GlucoseReading.user_id == user_id,
    )
    return db.scalar(statement)


def update_reading(
    db: Session, reading: GlucoseReading, data: GlucoseUpdate
) -> GlucoseReading:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(reading, field, value)
    db.commit()
    db.refresh(reading)
    return reading


def delete_reading(db: Session, reading: GlucoseReading) -> None:
    db.delete(reading)
    db.commit()
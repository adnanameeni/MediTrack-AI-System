from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.blood_pressure import (
    BloodPressureCreate,
    BloodPressureRead,
    BloodPressureUpdate,
)
from app.services import blood_pressure_service
from app.services.blood_pressure_service import InvalidPressurePairError

router = APIRouter(prefix="/blood-pressure", tags=["blood-pressure"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Reading not found",
    )


@router.post("", response_model=BloodPressureRead, status_code=status.HTTP_201_CREATED)
def create_blood_pressure_reading(
    payload: BloodPressureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return blood_pressure_service.create_reading(db, current_user.id, payload)


@router.get("", response_model=list[BloodPressureRead])
def list_blood_pressure_readings(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return blood_pressure_service.list_readings(db, current_user.id, limit, offset)


@router.get("/{reading_id}", response_model=BloodPressureRead)
def get_blood_pressure_reading(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = blood_pressure_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    return reading


@router.patch("/{reading_id}", response_model=BloodPressureRead)
def update_blood_pressure_reading(
    reading_id: int,
    payload: BloodPressureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = blood_pressure_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    try:
        return blood_pressure_service.update_reading(db, reading, payload)
    except InvalidPressurePairError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Systolic must be greater than diastolic",
        )


@router.delete("/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blood_pressure_reading(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = blood_pressure_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    blood_pressure_service.delete_reading(db, reading)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
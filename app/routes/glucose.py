from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.glucose import GlucoseCreate, GlucoseRead, GlucoseUpdate
from app.services import glucose_service

router = APIRouter(prefix="/glucose", tags=["glucose"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Reading not found",
    )


@router.post("", response_model=GlucoseRead, status_code=status.HTTP_201_CREATED)
def create_glucose_reading(
    payload: GlucoseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return glucose_service.create_reading(db, current_user.id, payload)


@router.get("", response_model=list[GlucoseRead])
def list_glucose_readings(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return glucose_service.list_readings(db, current_user.id, limit, offset)


@router.get("/{reading_id}", response_model=GlucoseRead)
def get_glucose_reading(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = glucose_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    return reading


@router.patch("/{reading_id}", response_model=GlucoseRead)
def update_glucose_reading(
    reading_id: int,
    payload: GlucoseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = glucose_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    return glucose_service.update_reading(db, reading, payload)


@router.delete("/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_glucose_reading(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reading = glucose_service.get_reading(db, current_user.id, reading_id)
    if reading is None:
        raise _not_found()
    glucose_service.delete_reading(db, reading)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
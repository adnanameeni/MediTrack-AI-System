from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.stats import MAX_RANGE, BloodPressureStats, GlucoseStats, as_utc
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


def _check_range(start: datetime, end: datetime) -> None:
    start, end = as_utc(start), as_utc(end)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end must be after start",
        )
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The date range cannot be longer than 366 days",
        )


@router.get("/glucose", response_model=GlucoseStats)
def glucose_statistics(
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_range(start, end)
    return stats_service.glucose_stats(db, current_user.id, start, end)


@router.get("/blood-pressure", response_model=BloodPressureStats)
def blood_pressure_statistics(
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_range(start, end)
    return stats_service.blood_pressure_stats(db, current_user.id, start, end)
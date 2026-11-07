from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "healthy"}


@router.get("/health/db")
def database_health_check(db: Session = Depends(get_db)):
    """Tells a deployment whether the database is reachable and has its tables.

    It answers only "ready" or "database_not_ready". Error details, the
    address of the database and its contents are never sent.
    """
    try:
        # Reads the users table (and its columns), so a missing table or a
        # missing column is noticed as well as a broken connection.
        db.execute(select(User.id, User.role, User.is_active).limit(1))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503, content={"status": "database_not_ready"})
    return {"status": "ready"}

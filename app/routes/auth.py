from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _email_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Email is already registered",
    )


def _bad_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise _email_taken()

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two signups with the same email at the same moment.
        db.rollback()
        raise _email_taken()
    db.refresh(user)
    return user


@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        # Spend similar time as a real check so timing does not reveal
        # whether the email exists.
        burn_password_check(payload.password)
        raise _bad_login()

    if not verify_password(payload.password, user.hashed_password):
        raise _bad_login()
    if not user.is_active:
        raise _bad_login()

    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user
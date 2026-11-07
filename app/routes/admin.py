from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.schemas.admin import (
    AdminOverview,
    AdminProfile,
    AdminUserDetail,
    AdminUserPage,
    AdminUserRead,
    AuditPage,
    Role,
    RoleChange,
    StatusChange,
)
from app.services import admin_service
from app.services.admin_service import (
    LastAdminError,
    SelfChangeError,
    UserNotFoundError,
)

# The administrator check is attached to the whole router, so every route
# added here is protected, even if someone forgets to ask for it.
# 401 = not logged in, 403 = logged in but not an administrator.
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _detail(db: Session, user: User) -> AdminUserDetail:
    return AdminUserDetail(
        **AdminUserRead.model_validate(user).model_dump(),
        **admin_service.user_counts(db, user.id),
    )


@router.get("/me", response_model=AdminProfile)
def admin_profile(admin: User = Depends(require_admin)):
    return admin


@router.get("/overview", response_model=AdminOverview)
def admin_overview(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return admin_service.get_overview(db, days)


@router.get("/users", response_model=AdminUserPage)
def list_users(
    search: str | None = Query(None, max_length=100),
    role: Role | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    users, total = admin_service.list_users(db, search, role, limit, offset)
    return AdminUserPage(
        items=[AdminUserRead.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = admin_service.get_user(db, user_id)
    except UserNotFoundError:
        raise _not_found()
    return _detail(db, user)


@router.patch("/users/{user_id}/role", response_model=AdminUserDetail)
def change_user_role(
    user_id: int,
    payload: RoleChange,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        user = admin_service.change_role(db, admin, user_id, payload.role)
    except UserNotFoundError:
        raise _not_found()
    except SelfChangeError:
        raise _conflict("You cannot remove your own administrator access")
    except LastAdminError:
        raise _conflict("The last active administrator cannot be removed")
    return _detail(db, user)


@router.patch("/users/{user_id}/status", response_model=AdminUserDetail)
def change_user_status(
    user_id: int,
    payload: StatusChange,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        user = admin_service.set_active(db, admin, user_id, payload.is_active)
    except UserNotFoundError:
        raise _not_found()
    except SelfChangeError:
        raise _conflict("You cannot deactivate your own account")
    except LastAdminError:
        raise _conflict("The last active administrator cannot be deactivated")
    return _detail(db, user)


@router.get("/activity", response_model=AuditPage)
def recent_activity(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, max_length=40),
    db: Session = Depends(get_db),
):
    items, total = admin_service.list_activity(db, limit, offset, action)
    return AuditPage(items=items, total=total, limit=limit, offset=offset)

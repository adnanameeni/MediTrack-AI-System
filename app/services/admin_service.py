"""Administrator logic: overview numbers, user management and the audit log.

Rules kept in one place:
- Only counts are returned about health records and conversations, never content.
- An administrator can never remove their own admin rights or deactivate
  themselves, and the last active administrator can never be removed.
- Every role or status change writes an audit entry in the same database
  transaction as the change itself.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    BloodPressureReading,
    ChatConversation,
    GlucoseReading,
    User,
)
from app.models.admin_audit import (
    ACTION_ADMIN_DEMOTED,
    ACTION_ADMIN_PROMOTED,
    ACTION_USER_ACTIVATED,
    ACTION_USER_DEACTIVATED,
    AdminAuditLog,
)
from app.models.user import ROLE_ADMIN, ROLE_USER, ROLES
from app.schemas.admin import (
    AdminOverview,
    AuditEntryRead,
    AuditPerson,
    RecentRegistrations,
    RecordTotals,
    RegistrationTrend,
    TrendPoint,
    UserTotals,
)
from app.schemas.stats import as_utc


class UserNotFoundError(Exception):
    """No user has that id."""


class SelfChangeError(Exception):
    """An administrator tried to lock themselves out."""


class LastAdminError(Exception):
    """The change would leave no active administrator."""


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def get_overview(
    db: Session, days: int, now: datetime | None = None
) -> AdminOverview:
    now = as_utc(now) if now is not None else datetime.now(timezone.utc)

    # Users by role and by active state.
    grouped = db.execute(
        select(User.role, User.is_active, func.count()).group_by(
            User.role, User.is_active
        )
    ).all()
    total = admins = active = active_admins = 0
    for role, is_active, number in grouped:
        total += number
        if role == ROLE_ADMIN:
            admins += number
        if is_active:
            active += number
            if role == ROLE_ADMIN:
                active_admins += number
    users = UserTotals(
        total=total,
        admins=admins,
        normal_users=total - admins,
        active=active,
        inactive=total - active,
        active_admins=active_admins,
    )

    records = RecordTotals(
        glucose_readings=_count(db, GlucoseReading),
        blood_pressure_readings=_count(db, BloodPressureReading),
        conversations=_count(db, ChatConversation),
    )

    # SQLite returns times without a time zone (they are UTC), so the day
    # buckets are worked out here and not in SQL.
    created = sorted(as_utc(value) for value in db.scalars(select(User.created_at)))

    def since(delta: timedelta) -> int:
        return sum(1 for value in created if value >= now - delta)

    recent = RecentRegistrations(
        last_24_hours=since(timedelta(hours=24)),
        last_7_days=since(timedelta(days=7)),
        last_30_days=since(timedelta(days=30)),
        latest_registration_at=created[-1] if created else None,
    )

    today = now.date()
    first_day = today - timedelta(days=days - 1)
    per_day = {first_day + timedelta(days=i): 0 for i in range(days)}
    for value in created:
        day = value.date()
        if day in per_day:
            per_day[day] += 1
    trend = RegistrationTrend(
        days=days,
        total=sum(per_day.values()),
        points=[TrendPoint(date=day, count=number) for day, number in per_day.items()],
    )

    return AdminOverview(
        generated_at=now,
        users=users,
        records=records,
        recent_registrations=recent,
        registration_trend=trend,
    )


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def _like_pattern(term: str) -> str:
    """Turn what was typed into a safe 'contains' pattern (no wildcards)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def list_users(
    db: Session,
    search: str | None,
    role: str | None,
    limit: int,
    offset: int,
) -> tuple[list[User], int]:
    conditions = []
    term = (search or "").strip()
    if term:
        pattern = _like_pattern(term)
        conditions.append(
            or_(
                func.lower(User.full_name).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"),
            )
        )
    if role is not None:
        conditions.append(User.role == role)

    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    users = list(
        db.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return users, total


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError
    return user


def user_counts(db: Session, user_id: int) -> dict[str, int]:
    """How many records a user has. Counts only, never the records."""

    def count(model) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            or 0
        )

    return {
        "glucose_reading_count": count(GlucoseReading),
        "blood_pressure_reading_count": count(BloodPressureReading),
        "conversation_count": count(ChatConversation),
    }


def _other_active_admins(db: Session, excluding_user_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == ROLE_ADMIN,
                User.is_active.is_(True),
                User.id != excluding_user_id,
            )
        )
        or 0
    )


def change_role(db: Session, actor: User, user_id: int, new_role: str) -> User:
    if new_role not in ROLES:
        raise ValueError("Unknown role")
    target = get_user(db, user_id)
    if target.role == new_role:
        return target  # nothing to change, so nothing is logged

    if new_role == ROLE_USER and target.role == ROLE_ADMIN:
        if target.id == actor.id:
            raise SelfChangeError
        if target.is_active and _other_active_admins(db, target.id) == 0:
            raise LastAdminError

    previous = target.role
    target.role = new_role
    db.add(
        AdminAuditLog(
            admin_user_id=actor.id,
            target_user_id=target.id,
            action=ACTION_ADMIN_PROMOTED if new_role == ROLE_ADMIN else ACTION_ADMIN_DEMOTED,
            detail=f"{previous} -> {new_role}",
        )
    )
    db.commit()
    db.refresh(target)
    return target


def set_active(db: Session, actor: User, user_id: int, is_active: bool) -> User:
    target = get_user(db, user_id)
    if target.is_active == is_active:
        return target

    if not is_active:
        if target.id == actor.id:
            raise SelfChangeError
        if (
            target.role == ROLE_ADMIN
            and _other_active_admins(db, target.id) == 0
        ):
            raise LastAdminError

    target.is_active = is_active
    db.add(
        AdminAuditLog(
            admin_user_id=actor.id,
            target_user_id=target.id,
            action=ACTION_USER_ACTIVATED if is_active else ACTION_USER_DEACTIVATED,
            detail=f"is_active -> {is_active}",
        )
    )
    db.commit()
    db.refresh(target)
    return target


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _person(user_id, full_name, email) -> AuditPerson | None:
    if user_id is None or full_name is None:
        return None
    return AuditPerson(id=user_id, full_name=full_name, email=email)


def list_activity(
    db: Session, limit: int, offset: int, action: str | None = None
) -> tuple[list[AuditEntryRead], int]:
    admin = aliased(User)
    target = aliased(User)
    conditions = []
    if action:
        conditions.append(AdminAuditLog.action == action)

    total = (
        db.scalar(select(func.count()).select_from(AdminAuditLog).where(*conditions))
        or 0
    )
    rows = db.execute(
        select(
            AdminAuditLog,
            admin.id,
            admin.full_name,
            admin.email,
            target.id,
            target.full_name,
            target.email,
        )
        .outerjoin(admin, AdminAuditLog.admin_user_id == admin.id)
        .outerjoin(target, AdminAuditLog.target_user_id == target.id)
        .where(*conditions)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    entries = [
        AuditEntryRead(
            id=entry.id,
            action=entry.action,
            detail=entry.detail,
            created_at=entry.created_at,
            admin=_person(a_id, a_name, a_email),
            target=_person(t_id, t_name, t_email),
        )
        for entry, a_id, a_name, a_email, t_id, t_name, t_email in rows
    ]
    return entries, total

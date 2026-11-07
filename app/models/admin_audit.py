from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

ACTION_ROLE_CHANGED = "role_changed"
ACTION_ADMIN_PROMOTED = "admin_promoted"
ACTION_ADMIN_DEMOTED = "admin_demoted"
ACTION_USER_ACTIVATED = "user_activated"
ACTION_USER_DEACTIVATED = "user_deactivated"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdminAuditLog(Base):
    """A record of one administrator action.

    Only actions taken after this table was created are recorded. Nothing is
    guessed or back-filled for earlier events.
    """

    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_log_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # None means the action was done from the command line (no logged-in admin).
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
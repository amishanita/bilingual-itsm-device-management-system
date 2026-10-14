"""Login accounts. A user may be linked to one employee record."""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import LANGUAGES, USER_ROLES, Base, TimestampMixin, in_list
from app.models.employee import Employee


class User(TimestampMixin, Base):
    """An application login with a role.

    employee_id is how an employee or manager is matched to their own data
    (devices, tickets, department). It is unique: one login per employee.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(in_list("role", USER_ROLES), name="role"),
        CheckConstraint(in_list("language", LANGUAGES), name="language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    # RESTRICT: an employee with a login cannot be hard-deleted.
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), unique=True
    )
    language: Mapped[str] = mapped_column(String(2), default="ja", server_default="ja")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    employee: Mapped[Employee | None] = relationship()

"""Employee records. Employees are never deleted; leavers get status "left"."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPLOYEE_STATUSES, Base, TimestampMixin, in_list


class Employee(TimestampMixin, Base):
    """A person in the company who can hold devices and request tickets."""

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(in_list("status", EMPLOYEE_STATUSES), name="status"),
        # Manager visibility is filtered by department, so this column is queried often.
        Index("ix_employees_department", "department"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    department: Mapped[str] = mapped_column(String(100))
    position: Mapped[str] = mapped_column(String(100))
    join_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")

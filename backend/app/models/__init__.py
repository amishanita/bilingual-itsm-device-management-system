"""ORM models. Importing this package registers every table on Base.metadata."""

from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.device_detail import DeviceDetail
from app.models.employee import Employee
from app.models.faq import FaqArticle
from app.models.kitting import KittingTask, KittingTemplate
from app.models.loan import DeviceLoan
from app.models.ticket import Ticket, TicketComment
from app.models.user import User

__all__ = [
    "Asset",
    "AuditLog",
    "Base",
    "ChatMessage",
    "ChatSession",
    "DeviceDetail",
    "DeviceLoan",
    "Employee",
    "FaqArticle",
    "KittingTask",
    "KittingTemplate",
    "Ticket",
    "TicketComment",
    "User",
]

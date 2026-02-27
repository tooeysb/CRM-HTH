"""
SQLAlchemy models package.
All models are imported here for Alembic auto-generation to detect changes.
"""

from src.models.account import GmailAccount
from src.models.base import Base
from src.models.contact import Contact
from src.models.email import Email, EmailTag
from src.models.email_queue import EmailQueue
from src.models.guardian_event import GuardianEvent
from src.models.job import SyncJob
from src.models.user import User

__all__ = [
    "Base",
    "User",
    "GmailAccount",
    "Contact",
    "Email",
    "EmailTag",
    "EmailQueue",
    "SyncJob",
    "GuardianEvent",
]

#!/usr/bin/env python
"""Create EmailQueue table for ID-first fetching strategy."""

from sqlalchemy import create_engine

from src.core.config import settings
from src.models import Base, EmailQueue

if __name__ == "__main__":
    print("Creating EmailQueue table...")

    engine = create_engine(settings.database_url)

    # Create just the EmailQueue table
    EmailQueue.__table__.create(engine, checkfirst=True)

    print("✅ EmailQueue table created successfully!")
    print(f"   Table: {EmailQueue.__tablename__}")
    print(f"   Columns: {[c.name for c in EmailQueue.__table__.columns]}")

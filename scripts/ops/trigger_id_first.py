#!/usr/bin/env python3
"""Trigger ID-first scan for procore-main account."""

import os

from celery import Celery

# Configure Celery
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("gmail_sync", broker=redis_url, backend=redis_url)

# Trigger the ID-first task
task = celery_app.send_task(
    "fetch_all_message_ids", args=["8f28b22f-cc5c-46c3-9114-1d8551192fa7", "procore-main"]
)

print("✅ Triggered ID-first scan for procore-main")
print(f"Task ID: {task.id}")
print("\nThis will use the NEW incremental processing:")
print("- Queue IDs every 10,000 collected")
print("- Spawn Phase 2 workers immediately")
print("- Phase 1 and Phase 2 run in parallel")

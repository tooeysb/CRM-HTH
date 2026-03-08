#!/usr/bin/env python3
import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("gmail_sync", broker=redis_url, backend=redis_url)

# Trigger scan for personal account using old method (since it uses pagination)
task = celery_app.send_task(
    "scan_gmail_task", args=["8f28b22f-cc5c-46c3-9114-1d8551192fa7", ["personal"]]
)

print("✅ Triggered scan for personal account (tooey@hth-corp.com)")
print(f"Task ID: {task.id}")
print("This will resume processing the remaining 522 emails")

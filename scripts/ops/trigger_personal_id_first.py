#!/usr/bin/env python3
import os
from celery import Celery

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery_app = Celery('gmail_sync', broker=redis_url, backend=redis_url)

# Trigger ID-first scan for personal account
task = celery_app.send_task(
    'fetch_all_message_ids',
    args=['8f28b22f-cc5c-46c3-9114-1d8551192fa7', 'personal']
)

print(f"✅ Switched personal account to ID-first architecture")
print(f"Task ID: {task.id}")
print(f"\nThis will:")
print(f"- Fetch ALL message IDs (including the missing 522)")
print(f"- Queue them incrementally every 10K IDs")
print(f"- Spawn Phase 2 workers to process in parallel")
print(f"- Should complete in a few minutes at high speed")

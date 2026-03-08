#!/usr/bin/env python3
"""Spawn Phase 2 workers for procore-main account to process 833K queued emails."""
import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("gmail_sync", broker=redis_url, backend=redis_url)

# Spawn 10 Phase 2 workers for procore-main account
account_id = "98f67c4a-b0e0-47e3-90d7-8cab2c56fc27"  # procore-main

for i in range(10):
    task = celery_app.send_task("fetch_message_batch", args=[account_id])
    print(f"✅ Spawned worker {i+1}/10, task ID: {task.id}")

print("\n🚀 Spawned 10 workers to process 833,372 queued emails")
print("Expected throughput: ~1,500+ emails/min with new rate limits")

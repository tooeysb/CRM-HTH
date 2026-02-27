#!/usr/bin/env python3
"""Spawn Phase 2 workers for personal account to process the 700 unclaimed IDs."""
import os
from celery import Celery

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery_app = Celery('gmail_sync', broker=redis_url, backend=redis_url)

# Personal account ID
account_id = '8f28b22f-cc5c-46c3-9114-1d8551192fa7'

# Spawn 7 Phase 2 workers (700 IDs / 100 batch size = 7 workers)
print(f"Spawning 7 Phase 2 workers for personal account...")

for i in range(7):
    task = celery_app.send_task(
        'fetch_message_batch',
        args=[account_id]
    )
    print(f"  Worker {i+1}/7: {task.id}")

print(f"\n✅ Spawned 7 workers to process 700 personal account emails")
print(f"Workers will claim and process batches of 100 IDs each")

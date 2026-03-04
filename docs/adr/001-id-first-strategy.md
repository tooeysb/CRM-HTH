# ADR-001: ID-First Parallel Processing Strategy

## Status
Accepted

## Context
The original `scan_gmail_task` runs five sequential phases in a single Celery task: fetch emails, detect themes, generate vault. For 1.16M emails across 3 accounts, this took 40+ hours due to Gmail API rate limits (40 QPS conservative) and sequential account processing.

## Decision
Implement a two-phase "ID-first" parallel strategy (`id_first_tasks.py`):

1. **Phase 1** collects all Gmail message IDs into an `EmailQueue` table using lightweight `messages.list` calls (no full message fetch). This is fast since only IDs are returned.

2. **Phase 2** spawns up to 10 parallel workers that claim batches of IDs from the queue using `SELECT ... FOR UPDATE SKIP LOCKED`. Each worker fetches the full message content and inserts into the `emails` table.

### Self-healing behavior
- Workers mark claimed IDs as `status='fetching'` with a `claimed_at` timestamp
- A cleanup query reclaims IDs that have been in `fetching` state for 15+ minutes (zombie recovery)
- Duplicate emails are handled by `INSERT ON CONFLICT DO NOTHING` on `(account_id, gmail_message_id)`

## Consequences
- **5x speedup**: 10 parallel workers with independent rate limiting
- **Resilient**: Workers crash-restart without losing progress; stale claims auto-recover
- **Complexity**: Two-task coordination vs. single-task simplicity
- **Database load**: `SKIP LOCKED` polling adds minor overhead but avoids message broker fan-out

## Alternatives Considered
- **Celery chord/group**: Rejected because Gmail rate limits are per-user, not per-worker. Coordinating rate limits across a Celery group requires shared state (Redis), which we already handle with the token bucket.
- **Single task with async I/O**: Rejected because the Gmail client library is synchronous and wrapping it in threads adds complexity without the self-healing benefits.

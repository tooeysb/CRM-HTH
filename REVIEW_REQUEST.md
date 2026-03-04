# Architecture Review Request: Gmail Email Body Backfill System

## For: Quality Review Agent
## Status: LIVE AND RUNNING — architecture review requested while backfill is in progress

---

## Mission

We are backfilling full email bodies for **1,162,095 emails** across 3 Gmail accounts. These emails were originally fetched with `format="metadata"` (headers only). We now need to re-fetch each one with `format="full"` to extract the plain-text body and store it in a new `body` column on the `emails` table.

**We are open to a fully new architecture from scratch.** The current implementation works but we want your review to determine whether this is state-of-the-art and maximizes throughput. If you identify a better approach, propose it — don't feel constrained by the existing design.

---

## Account-Level Rate Limits (CRITICAL CONTEXT)

| Account | Type | Emails | Gmail API Quota |
|---------|------|--------|-----------------|
| tooey@procore.com | Google Workspace | 1,050,738 | **15,000 quota units/min (250 QPS)** |
| 2e@procore.com | Google Workspace | 87,100 | **15,000 quota units/min (250 QPS)** |
| tooey@hth-corp.com | Consumer Gmail | 26,476 | ~250 QPM (conservative) |

**Key constraint**: Each `messages.get` call costs **5 quota units**. So 15,000 QPM = 3,000 messages/min theoretical max for Workspace accounts. The Gmail Batch API bundles up to 100 sub-requests per HTTP call, but each sub-request still costs 5 quota units individually.

**Concurrent connection limit**: Gmail allows ~10-20 simultaneous HTTP connections per user. Exceeding this returns 429 errors.

---

## Current Architecture

### Source Files

| File | Role |
|------|------|
| `src/worker/backfill_body_tasks.py` | Celery task definitions (entry point + worker) |
| `src/integrations/gmail/client.py` | Gmail API client with batch fetch |
| `src/integrations/gmail/rate_limiter.py` | Token bucket rate limiter (Redis-backed) |
| `src/worker/celery_app.py` | Celery configuration |
| `src/models/email.py` | Email SQLAlchemy model (has new `body` column) |

### Data Flow

```
1. start_body_backfill(account_id)
   └── Counts emails WHERE body IS NULL
   └── Spawns N parallel backfill_worker tasks via Celery group

2. backfill_worker(account_id)  [runs as Celery task]
   ├── SELECT id, gmail_message_id FROM emails
   │   WHERE account_id = ? AND body IS NULL
   │   LIMIT 100
   │   FOR UPDATE SKIP LOCKED
   │
   ├── UPDATE emails SET body = '__fetching__' WHERE id IN (claimed_ids)
   │   (sentinel value prevents re-claiming by other workers)
   │
   ├── db.close()  ← CRITICAL: closes DB before Gmail fetch to avoid SSL timeout
   │
   ├── Create per-account GmailRateLimiter
   │   ├── Workspace: 200 max_tokens, 50 tokens/sec refill
   │   └── Consumer: 50 max_tokens, 10 tokens/sec refill
   │   └── Redis key: gmail:backfill:{account_id}:tokens (ISOLATED per account)
   │
   ├── gmail_client.fetch_message_batch(gmail_ids, format="full")
   │   └── Chunks into groups of 20
   │   └── Each chunk: rate_limiter.wait_for_token(tokens=20)
   │   └── Each chunk: Gmail Batch API call with 20 sub-requests
   │
   ├── db = SessionLocal()  ← reopen DB connection
   │
   ├── UPDATE emails SET body = ? WHERE gmail_message_id = ?
   │   (for each email that had body content)
   │
   ├── UPDATE emails SET body = '' WHERE id IN (no_body_ids)
   │   (image-only emails etc. — marks as "done, no text" so not re-fetched)
   │
   ├── On error: UPDATE emails SET body = NULL WHERE id IN (claimed_ids)
   │   (resets sentinel so failed rows get retried)
   │
   └── Check remaining → if > 0, spawn replacement: backfill_worker.delay(account_id)
       (self-sustaining chain)
```

### Parallel Execution Model

```
Celery Worker Pool (concurrency=15)
├── Account: tooey@procore.com (5 workers)
│   ├── Worker 1: claims 100 → fetches → writes → spawns replacement
│   ├── Worker 2: claims 100 → fetches → writes → spawns replacement
│   ├── Worker 3: claims 100 → fetches → writes → spawns replacement
│   ├── Worker 4: claims 100 → fetches → writes → spawns replacement
│   └── Worker 5: claims 100 → fetches → writes → spawns replacement
├── Account: 2e@procore.com (5 workers)
│   └── (same pattern, separate rate limiter bucket)
└── Account: tooey@hth-corp.com (5 workers)
    └── (same pattern, separate rate limiter bucket, lower QPS)
```

Each worker is a self-sustaining chain: when it finishes a batch, it spawns a replacement Celery task. If it fails, the sentinel is cleared and those rows become available for other workers.

### Rate Limiter Implementation

The rate limiter uses a **token bucket algorithm** backed by Redis with an **atomic Lua script**:

```lua
-- Atomic token acquire (no TOCTOU race conditions)
local current_tokens = redis.call('GET', bucket_key) or max_tokens
local elapsed = now - last_refill
local new_tokens = min(current_tokens + elapsed * refill_rate, max_tokens)
if new_tokens >= tokens_requested then
    new_tokens = new_tokens - tokens_requested
    -- ... update and return 1 (acquired)
else
    -- ... return 0 (denied)
end
```

**Per-account isolation**: Each account gets its own Redis keys:
- `gmail:backfill:{account_id}:tokens`
- `gmail:backfill:{account_id}:last_refill`

This means workers for different accounts never compete for tokens. Workers for the SAME account share that account's token pool.

**Token consumption**: `fetch_message_batch` chunks 100 IDs into groups of 20. Each chunk requests `tokens=20` from the rate limiter (one token per messages.get sub-request in the batch).

### Database Connection Management

**Problem solved**: Supabase/PgBouncer drops SSL connections after ~60 seconds of inactivity. A Gmail batch fetch of 100 emails can take 5-15 seconds, which sometimes triggers the timeout.

**Solution**: The worker closes the DB session BEFORE making Gmail API calls and reopens it AFTER. This pattern was proven in the existing `tasks.py` for the forward pipeline.

### Sentinel Value Pattern

Instead of using a separate queue table (which was the original design and added overhead), we use the `body` column itself as the state machine:

| body value | State | Meaning |
|------------|-------|---------|
| `NULL` | Unclaimed | Ready to be picked up by a worker |
| `'__fetching__'` | In progress | Claimed by a worker, Gmail fetch in progress |
| `''` (empty string) | Done (no content) | Email has no text body (image-only, etc.) |
| `'actual text...'` | Done | Body successfully fetched and stored |

This eliminates the need for a separate `email_queue` table, reducing JOIN overhead and simplifying the data model.

### Error Recovery

1. **Worker crashes during Gmail fetch**: The sentinel `__fetching__` stays in the DB. These rows need manual cleanup (or a periodic sweep task) to reset to NULL.
2. **Gmail API error (429, timeout, etc.)**: Caught in the except block, sentinel is reset to NULL, rows become available for retry. Exception is re-raised so Celery can track the failure.
3. **DB write error after successful Gmail fetch**: Currently would lose the fetched data. The Gmail fetch would need to be repeated.
4. **Worker completes but can't spawn replacement**: Caught silently. Other active workers will continue, and the backfill can be re-triggered manually.

---

## Observed Performance

| Metric | Value |
|--------|-------|
| Batch size | 100 emails per worker cycle |
| Chunk size | 20 emails per Gmail Batch API call |
| Worker cycle time | ~15 seconds (including DB claim, Gmail fetch, DB write) |
| Workers per account | 5 |
| Celery concurrency | 15 (5 per account x 3 accounts) |
| **Current throughput** | **~3,400 emails/minute (measured, all 3 accounts combined)** |
| Theoretical max (procore alone) | 3,000 emails/min (15,000 QPM / 5 units per msg) |
| Theoretical max (all 3 accounts) | ~6,500 emails/min (2 Workspace + 1 consumer) |

---

## Questions for Reviewer

### 1. Throughput Optimization
- Are we leaving significant throughput on the table? With 15,000 QPM for Workspace accounts, we should be able to do 3,000 messages/min per account. Our current rate seems well below that.
- Should batch chunk size be larger than 20? The Gmail Batch API supports up to 100 sub-requests per batch call. Would larger chunks reduce HTTP overhead?
- Is 5 workers per account optimal? Should we increase for the procore.com account given its higher quota?

### 2. Rate Limiter Design
- The token bucket refills at 50 tokens/sec for Workspace accounts. Is this correctly calibrated to the 15,000 QPM limit? (15,000 / 60 = 250 QPS for quota units; each msg = 5 units; so 50 msg/sec matches)
- With 5 workers sharing 50 tokens/sec and each requesting 20 tokens per chunk, are we creating starvation? (5 workers x 20 tokens = 100 tokens needed simultaneously vs 200 max bucket)
- Should we implement a queuing/fairness mechanism instead of first-come-first-served token acquisition?

### 3. Architecture Alternatives
- **We are fully open to replacing this entire architecture.** If there's a better pattern for maximum throughput Gmail body backfill, propose it.
- Would `asyncio` + `aiohttp` outperform the Celery + sync approach?
- Would a producer-consumer pattern with a shared work queue be better than self-sustaining worker chains?
- Should we use connection pooling differently?

### 4. Reliability
- The sentinel pattern leaves `__fetching__` rows if a worker dies. Should we add a periodic cleanup task or use a timestamp-based expiry?
- Is `FOR UPDATE SKIP LOCKED` the right locking strategy? Would advisory locks or row-level versioning be better?
- Should we implement a circuit breaker to back off when Gmail returns 429s?

### 5. Database Performance
- Each worker issues individual UPDATEs per email (inside a loop). Should we batch these into a single `UPDATE ... FROM VALUES` statement?
- The `WHERE body IS NULL` filter scans potentially millions of rows. Should we add a partial index: `CREATE INDEX idx_emails_null_body ON emails(account_id) WHERE body IS NULL`?

---

## File Locations for Review

```
src/worker/backfill_body_tasks.py       # Main backfill logic (250 lines)
src/integrations/gmail/client.py        # Gmail API client, fetch_message_batch() at line 198
src/integrations/gmail/rate_limiter.py  # Token bucket rate limiter (262 lines)
src/models/email.py                     # Email model with body column
src/worker/celery_app.py                # Celery config and task registration
```

---

## Success Criteria

1. **All 1,162,095 emails have body != NULL** (either actual text or empty string for no-content emails)
2. **No data corruption** — emails that already have bodies are never overwritten
3. **Throughput approaches theoretical maximum** — especially for the procore.com account (3,000 msg/min)
4. **Self-healing** — if workers crash, the system recovers without manual intervention
5. **Completes in reasonable time** — at current 3,400/min combined rate, ~342 min (~5.7 hours) for all 1.16M emails. At theoretical max (~6,500/min), could be ~3 hours. Are we leaving half the throughput on the table?

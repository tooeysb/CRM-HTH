# Architecture Review: Gmail Email Body Backfill System

**Reviewer**: Senior Infrastructure/Performance Engineer
**Date**: 2026-03-01
**Status**: Live system processing 1,162,095 emails across 3 Gmail accounts

---

## Executive Summary

The current system achieves ~3,400 emails/min against a theoretical ceiling of ~6,250 emails/min -- utilizing roughly **54% of available quota**. The gap is not caused by a single bottleneck but by five compounding inefficiencies that each shave 5-15% off throughput. The most impactful changes are: (1) increasing Gmail batch chunk size from 20 to 100, (2) increasing Celery concurrency from 15 to 20+ and rebalancing workers per account, (3) batching database writes, and (4) adding a partial index on `body IS NULL`. Together these changes should push throughput to ~5,500-6,000 emails/min without an architecture rewrite.

If a clean-sheet redesign is acceptable, an asyncio-based approach with `aiohttp` and connection pooling would remove all the overhead of Celery task scheduling, Redis round-trips for chaining, and synchronous blocking, and could realistically saturate the Gmail quotas at ~6,200+ emails/min.

---

## 1. Throughput Analysis: Why 3,400/min Instead of 6,500/min

### 1.1 Theoretical Maximum Calculation

| Account | Quota (QPM) | Units per msg.get | Max msgs/min | Max msgs/sec |
|---------|-------------|-------------------|-------------|--------------|
| tooey@procore.com | 15,000 | 5 | 3,000 | 50 |
| 2e@procore.com | 15,000 | 5 | 3,000 | 50 |
| tooey@hth-corp.com | ~250 | 5 | ~50 | ~0.83 |
| **Combined** | | | **~6,050** | **~100.83** |

Note: The review request says ~6,500/min but the consumer account caps at ~50/min, not ~500/min. True theoretical max is approximately **6,050 emails/min**.

Current throughput: **3,400/min = 56% utilization**.

### 1.2 Where the Missing 44% Goes

I identified five compounding sources of waste:

#### Source 1: Small Batch Chunk Size (estimated loss: ~15-20%)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/client.py`, line 231

```python
chunk_size = 20
```

The code comments reference a "concurrent connection limit of ~10-20" as justification. However, this conflates two different concepts:

- **Concurrent HTTP connections per user**: ~10-20 simultaneous open connections
- **Sub-requests per batch HTTP call**: up to 100 per single connection

A Gmail Batch API call is a **single HTTP request** containing multiple sub-requests encoded as multipart MIME. It uses **one** connection, not N connections. Increasing chunk_size from 20 to 100 means 5x fewer HTTP round-trips per batch of 100 emails. Each HTTP request has ~50-150ms of overhead (TLS, TCP, serialization). For 100 emails:

- Current: 5 HTTP requests x ~100ms overhead = ~500ms wasted
- Proposed: 1 HTTP request x ~100ms overhead = ~100ms wasted
- **Savings: ~400ms per 100 emails = ~8 seconds per minute per worker**

With 10 Workspace workers, that is ~80 seconds of cumulative overhead eliminated per wall-clock minute -- roughly equivalent to 1 extra worker's output.

#### Source 2: Celery Task Overhead per 100-Email Cycle (estimated loss: ~10-15%)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, lines 95-249

Each 100-email cycle includes:

1. **Task dispatch + deserialization**: ~10-50ms (Redis broker round-trip)
2. **DB query to claim batch** (lines 115-124): SELECT with FOR UPDATE SKIP LOCKED over potentially millions of rows without a partial index: **100-500ms**
3. **UPDATE to set sentinel** (lines 134-139): 100 individual row updates: ~50-100ms
4. **GmailAccount lookup** (line 108): ORM query for account credentials: ~20-50ms
5. **Remaining count query** (lines 227-234): Full COUNT(*) over potentially 1M+ rows with `body IS NULL`: **200-1000ms**
6. **Self-chain spawn** (line 241): Redis publish for new task: ~10-20ms

Conservative estimate: **500-1500ms of non-Gmail overhead per 100-email cycle**. With a Gmail fetch time of ~2-5 seconds for 100 emails (at 50/sec rate limit), the overhead is **20-40% of total cycle time**.

#### Source 3: Rate Limiter Polling Delay (estimated loss: ~5-10%)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/rate_limiter.py`, line 177

```python
sleep_time = min(1.0 / self.refill_rate, 0.1)
```

For Workspace accounts with `refill_rate=50.0`, `sleep_time = min(0.02, 0.1) = 0.02s`. This is fine individually, but consider the worst case: a worker requests 20 tokens and the bucket has 19. It sleeps 20ms, then retries. In 20ms at 50 tokens/sec, only 1 token refills -- still not enough. It may need multiple retries. With 5 workers all contending for the same bucket, this creates a thundering-herd pattern where all workers poll simultaneously, most fail, and they all sleep again.

More critically, when using chunk_size=20, each of the 5 workers requests 20 tokens. The bucket max is 200 and refills at 50/sec. Five simultaneous requests for 20 tokens = 100 tokens. If the bucket has drained to <100, some workers must wait. In the steady state, 50 tokens arrive per second but 5 workers want to consume at their maximum rate -- the bucket acts as a **serialization point** creating lock-step behavior instead of pipelining.

#### Source 4: Sequential Gmail Chunks Within a Worker (estimated loss: ~5%)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/client.py`, lines 232-235

```python
for i in range(0, len(message_ids), chunk_size):
    chunk = message_ids[i:i + chunk_size]
    batch_emails = self._fetch_batch_chunk(chunk, format)
    emails.extend(batch_emails)
```

Each chunk is fetched sequentially. With chunk_size=20 and batch_size=100, this is 5 serial HTTP calls. Even with chunk_size=100, a single worker can never have more than one HTTP request in flight. If the Gmail API takes 500ms to respond to a batch of 100, the worker is blocked for that entire 500ms and no pipeline overlap is possible.

#### Source 5: `worker_max_tasks_per_child = 10` Creates Unnecessary Worker Restarts

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/celery_app.py`, line 29

```python
"worker_max_tasks_per_child": 10,
```

Each Celery child process restarts after processing 10 tasks. With 15 concurrent workers each processing a batch of 100 emails, the pool recycles every 150 cycles (15,000 emails). Process restart cost is ~500ms-2s depending on imports and GmailClient initialization (which includes a `googleapiclient.discovery.build()` call). Over the lifetime of 1.16M emails, that is ~77 restarts x ~1s = ~77 seconds of lost time. Minor but unnecessary for this workload.

### 1.3 Throughput Gap Summary

| Source | Estimated Impact | Fix Difficulty |
|--------|-----------------|----------------|
| Small chunk size (20 vs 100) | 15-20% | Trivial (one-line) |
| Per-cycle Celery/DB overhead | 10-15% | Medium |
| Rate limiter contention | 5-10% | Medium |
| Sequential chunks (no pipelining) | 5% | Medium |
| Worker restarts | <1% | Trivial |
| **Total estimated loss** | **~36-50%** | |

This lines up with the observed 44% gap.

---

## 2. Rate Limiter Review

### 2.1 Calibration Check

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/rate_limiter.py`

For the `tooey@procore.com` account:
- `max_tokens = 200`, `refill_rate = 50.0`

Gmail quota: 15,000 quota units/min = 250 quota units/sec. Each `messages.get` = 5 quota units, so max 50 messages/sec.

The rate limiter tracks **messages** not **quota units**, so `refill_rate=50.0` messages/sec is correct. The bucket max of 200 allows a burst of 200 messages (= 1,000 quota units = 4 seconds of quota) before throttling. This is reasonable.

**Verdict**: Calibration is correct.

### 2.2 Token Starvation Analysis

With 5 workers per Workspace account, each requesting 20 tokens per chunk:

- **Demand**: 5 workers x (100 emails / 20 per chunk) = 25 chunk requests per cycle
- **Supply**: 50 tokens/sec, so 20 tokens refill in 0.4 seconds
- **Steady-state**: Workers can collectively consume 50 msgs/sec, which matches supply

The problem is not aggregate throughput but **bursty contention**. When all 5 workers finish their previous chunk at roughly the same time and simultaneously request 20 tokens, only the first 2-3 succeed (if bucket has 40-60 tokens). The remaining workers enter the polling loop with 20ms sleeps.

With chunk_size=100, this gets worse: 5 workers each request 100 tokens simultaneously against a 200-token bucket. At most 2 can succeed, and the remaining 3 wait for 2+ seconds each.

### 2.3 Recommendations for Rate Limiter

**Problem**: The `wait_for_token` polling loop (line 159) is a spin-wait that wastes CPU and introduces unpredictable latency.

**Better approach**: Return the **wait time** from the Lua script so the caller can sleep exactly the right amount instead of polling.

Improved Lua script sketch:
```lua
if new_tokens >= tokens_requested then
    new_tokens = new_tokens - tokens_requested
    redis.call('SET', bucket_key, tostring(new_tokens))
    redis.call('SET', timestamp_key, tostring(now))
    return 0  -- acquired, zero wait
else
    local deficit = tokens_requested - new_tokens
    local wait_time = deficit / refill_rate
    -- Still update timestamp to prevent other callers from double-counting refill
    redis.call('SET', bucket_key, tostring(new_tokens))
    redis.call('SET', timestamp_key, tostring(now))
    return wait_time  -- caller should sleep this long
end
```

Python side:
```python
def wait_for_token(self, tokens: int = 1, timeout: float = 60.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        wait_time = self._acquire_script(
            keys=[self.bucket_key, self.timestamp_key],
            args=[self.max_tokens, self.refill_rate, tokens, time.time()],
        )
        wait_time = float(wait_time)
        if wait_time == 0:
            return  # acquired
        time.sleep(wait_time + 0.005)  # small buffer
    raise GmailRateLimitExceeded(...)
```

This eliminates the polling loop entirely. Each denied caller sleeps for exactly the time needed and retries once, removing the thundering herd.

### 2.4 Are 5 Workers Per Account Optimal?

No. The optimal count depends on the **ratio of Gmail API latency to rate-limit wait time**.

For a Workspace account at 50 msgs/sec with chunk_size=100:
- Time to accumulate 100 tokens: 2 seconds
- Gmail API latency for a batch of 100: ~0.5-1.5 seconds
- DB overhead per cycle: ~0.5-1.0 seconds
- **Total cycle time**: ~3-4.5 seconds per 100 emails

To keep the rate limiter fully utilized, you need enough workers that one is always ready to consume tokens as they refill. With a 2-second token accumulation window and a 3-4.5 second cycle, you need ceil(4.5 / 2) = **3 workers** to keep the pipeline full for one account.

Five workers is slightly over-provisioned which is fine -- the extra 2 workers act as buffer for variance. However, for the consumer account (`tooey@hth-corp.com` at 10 msgs/sec), 5 workers is excessive. Token accumulation for 100 emails at 10/sec = 10 seconds. One or two workers would suffice.

**Recommendation**:
- Workspace accounts: 5-7 workers (keep current or slightly increase)
- Consumer account: 2 workers
- Reallocate the freed 3 Celery slots to the `procore.com` account (which has 92% of the emails)

---

## 3. Architecture Assessment

### 3.1 Is Celery the Right Tool?

Celery is designed for **task queues** -- discrete, independent units of work dispatched to a worker pool. The backfill workload is a **streaming pipeline**: read IDs, fetch from API, write to DB, repeat. Using Celery adds:

1. **Redis round-trip per task dispatch**: ~5-10ms to publish, ~5-10ms to consume
2. **JSON serialization/deserialization**: Each task's arguments are serialized to JSON, published to Redis, consumed, and deserialized
3. **Task acknowledgment protocol**: Celery's `ack_late` setting means tasks are re-delivered if a worker dies, but this adds bookkeeping overhead
4. **Self-chaining overhead**: Each worker spawns a new Celery task after finishing (line 241), adding an unnecessary dispatch cycle every 100 emails

The self-sustaining chain pattern means the system does 15,000+ Celery task dispatches per minute just for the chaining mechanism. Each involves a Redis PUBLISH, a worker consuming the message, deserializing it, and running the task setup code. This is ~150ms of overhead per chain x 100/min = ~15 seconds/min wasted per worker.

### 3.2 Would asyncio Be Fundamentally Better?

**Yes, for this specific workload.** Here is why:

The backfill task is **I/O-dominated**: >90% of time is spent waiting for Gmail API responses and database writes. Synchronous Celery workers use OS threads (prefork pool) that are blocked during I/O. An async approach can multiplex many concurrent API calls on a single thread.

Key advantages of asyncio for this workload:

1. **Eliminate task dispatch overhead**: No Redis round-trips for chaining. A simple `while` loop replaces the self-sustaining chain.
2. **Pipeline Gmail fetches**: While one batch of 100 is in-flight, the next batch's tokens can be acquired and the next batch's IDs can be claimed from the DB. True pipelining of fetch/write/claim.
3. **Finer-grained concurrency**: Instead of 5 workers each doing 1 HTTP call at a time, a single async loop can have 5 HTTP calls in flight simultaneously with precise rate-limiting.
4. **Simpler error recovery**: No Celery task state to manage. A failed fetch just retries in the same loop iteration.

**Estimated improvement**: 20-30% throughput gain from eliminating Celery overhead and enabling pipelining.

### 3.3 Proposed Alternative Architecture (Clean-Sheet)

If you are open to replacing the architecture, here is the optimal design for maximum throughput:

```
                  +--------------------------+
                  |    Orchestrator Script    |
                  |  (python backfill.py)     |
                  +----+------+------+-------+
                       |      |      |
              +--------+  +---+---+  +--------+
              |           |       |            |
         asyncio.Task  asyncio.Task  asyncio.Task
         (procore)     (2e)          (personal)
              |           |            |
        AccountPipeline  AccountPipeline  AccountPipeline
              |           |            |
     +--------+--------+ | ...        | ...
     |        |        |
   Fetcher  Fetcher  Fetcher   (N concurrent fetchers per account)
     |        |        |
     +--------+--------+
              |
         BatchWriter  (single writer per account, batched UPDATEs)
```

Each `AccountPipeline` is an `asyncio.Task` that:

1. Claims a batch of IDs from the DB (async query)
2. Fans out to N concurrent fetchers (each making a Batch API call of 100)
3. Collects results into a write buffer
4. Periodically flushes the write buffer with a single batched UPDATE

```python
# Sketch of the core loop for one account
import asyncio
import aiohttp
from asyncpg import create_pool

async def account_pipeline(account_id: str, creds: dict, rate_limiter, db_pool):
    """Process all emails for one account."""
    while True:
        # 1. Claim batch from DB (async, no Celery overhead)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                UPDATE emails SET body = '__fetching__', updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM emails
                    WHERE account_id = $1 AND body IS NULL
                    LIMIT 500
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, gmail_message_id
            """, account_id)

        if not rows:
            break  # Done

        gmail_ids = [r['gmail_message_id'] for r in rows]
        id_map = {r['gmail_message_id']: r['id'] for r in rows}

        # 2. Fetch from Gmail in parallel chunks of 100
        chunks = [gmail_ids[i:i+100] for i in range(0, len(gmail_ids), 100)]
        results = []
        for chunk in chunks:
            await rate_limiter.acquire(len(chunk))  # async wait
            result = await gmail_batch_fetch(session, creds, chunk)
            results.extend(result)

        # 3. Batched DB write (single statement for all 500)
        async with db_pool.acquire() as conn:
            await conn.executemany("""
                UPDATE emails SET body = $2, updated_at = NOW()
                WHERE id = $1
            """, [(id_map[r['gmail_message_id']], r['body'] or '') for r in results])

async def main():
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            account_pipeline("procore-id", procore_creds, procore_limiter, db_pool),
            account_pipeline("2e-id", twoe_creds, twoe_limiter, db_pool),
            account_pipeline("personal-id", personal_creds, personal_limiter, db_pool),
        )
```

**Key differences from current architecture**:
- No Celery, no Redis broker overhead, no task serialization
- Direct async DB access via `asyncpg` (no ORM overhead for this simple UPDATE workload)
- Larger claim batches (500 instead of 100) to reduce claim frequency
- Single batched UPDATE instead of per-row updates
- True parallel fetches within each account pipeline
- Clean `while True` loop instead of self-sustaining chain

**Estimated throughput**: 5,500-6,000 emails/min (90-99% of theoretical maximum).

### 3.4 Pragmatic Recommendation

Given the system is **already live and running**, a full rewrite carries risk. The pragmatic path is to apply the high-impact changes to the existing Celery architecture first, which should get throughput to ~5,000-5,500/min. If that is still insufficient, then consider the async rewrite.

---

## 4. Reliability Gaps

### 4.1 Stuck `__fetching__` Rows (CRITICAL)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`

The review request document (line 149) acknowledges this: if a worker process is killed (OOM, Heroku dyno restart, SIGKILL), the `__fetching__` sentinel is never cleared. Those rows become permanently stuck.

**Current state**: There is no cleanup mechanism. The only recovery is manual SQL.

**Quantitative risk**: With `worker_max_tasks_per_child=10` and `task_acks_late=True`, Celery can re-deliver a task if a worker dies. But the sentinel rows from the **previous** execution of that task are already marked `__fetching__` and will not be reclaimed by the re-delivered task (it will claim **new** rows with `body IS NULL`). Over a 5-hour backfill, if even 1% of cycles experience a hard kill, that is ~58 cycles x 100 emails = ~5,800 stuck emails.

**Recommendation**: Add a periodic Celery beat task that runs every 5 minutes:

```python
@celery_app.task(name="cleanup_stuck_fetching")
def cleanup_stuck_fetching():
    """Reset emails stuck in __fetching__ state for more than 10 minutes."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        result = db.execute(
            update(Email)
            .where(
                Email.body == "__fetching__",
                Email.updated_at < cutoff,
            )
            .values(body=None)
        )
        if result.rowcount > 0:
            logger.warning(f"Reset {result.rowcount} stuck __fetching__ emails")
        db.commit()
    finally:
        db.close()
```

This relies on `updated_at` being set when the sentinel is written (which it currently is NOT -- line 137 only sets `body`, not `updated_at`). Fix: add `updated_at=datetime.utcnow()` to the sentinel UPDATE.

### 4.2 Worker Death and Chain Breakage

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, line 241

The self-sustaining chain pattern means if a worker dies after completing its batch but before spawning a replacement (line 241), that account loses one worker permanently. Over time, with `worker_max_tasks_per_child=10` causing process restarts, there is a non-zero chance of chain breakage reducing active workers.

The mitigation is that `task_acks_late=True` and `task_reject_on_worker_lost=True` (celery_app.py lines 30-31) cause Celery to re-deliver unacknowledged tasks. However, the self-chaining spawn at line 241 happens **inside** the task, after the main work is done but before the task returns. If the process dies between line 241 (spawn) and the `finally` block, the task is re-delivered, and now **two** chains exist for that account -- one from the re-delivered task and one from the spawned replacement. This is a "chain multiplication" bug that could cause the worker count per account to grow over time.

**Recommendation**: Replace self-sustaining chains with a simpler monitoring loop. Use Celery Beat to periodically check if enough workers are running per account and spawn replacements as needed. This decouples "doing work" from "maintaining the worker population."

### 4.3 Error Recovery on DB Write Failure (Line 213)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, lines 213-223

The review request (line 152) notes: "DB write error after successful Gmail fetch: Currently would lose the fetched data." This is correct. If the DB write at line 206 fails (e.g., Supabase connection timeout), the `except` block at line 213 catches the exception, resets the sentinel to NULL, and re-raises. The Gmail API responses are lost and must be re-fetched.

**Impact**: Each lost batch costs 100 Gmail API calls (500 quota units) and ~2-5 seconds. If Supabase has a brief outage (e.g., 30 seconds), all 15 active workers lose their current batches = 1,500 wasted API calls.

**Mitigation**: Write fetched bodies to a local buffer (file or Redis hash) before attempting the DB write. On DB failure, retry the DB write from the buffer without re-fetching from Gmail. However, this adds complexity. Given the low probability and self-healing nature (rows reset to NULL and get retried), this is acceptable for the current workload.

### 4.4 No Circuit Breaker for Gmail 429s

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/client.py`, line 288

When Gmail returns a 429 (rate limit exceeded), the `HttpError` is caught and re-raised as `GmailClientError`. The `@with_retry` decorator (line 197) retries with exponential backoff. However, the rate limiter does not react to 429s -- it continues issuing tokens at the same rate. All 5 workers for that account will independently hit the 429, back off, and retry, creating a burst of retried requests that may trigger another 429.

**Recommendation**: When a 429 is received, drain the rate limiter bucket to zero and reduce the refill rate temporarily:

```python
def report_rate_limit_hit(self):
    """Called when Gmail returns 429. Pauses token generation."""
    self.redis_client.set(self.bucket_key, "0")
    # Other workers will see zero tokens and wait for refill
```

### 4.5 `FOR UPDATE SKIP LOCKED` Without Partial Index

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, lines 115-124

The query:
```python
db.query(Email.id, Email.gmail_message_id)
    .filter(Email.account_id == account_id, Email.body == None)
    .limit(BATCH_SIZE)
    .with_for_update(skip_locked=True)
    .all()
```

Without a partial index, PostgreSQL must scan the `emails` table (or the `account_id` index) to find rows where `body IS NULL`. As the backfill progresses and fewer rows have NULL bodies, the scan becomes increasingly expensive because it must skip over millions of already-processed rows to find the remaining NULL ones.

At 90% completion (~100K rows remaining out of 1.16M), the query planner may choose a sequential scan or a long index scan, potentially taking **seconds per query**. With 15 workers all running this query concurrently, this becomes a major bottleneck.

---

## 5. Database Performance

### 5.1 Per-Row UPDATEs (CRITICAL -- Easy Win)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, lines 182-191

```python
for gmail_id, body in body_map.items():
    db.execute(
        update(Email)
        .where(Email.account_id == account_id_uuid, Email.gmail_message_id == gmail_id)
        .values(body=body, updated_at=datetime.utcnow())
    )
    updated += 1
```

This issues up to 100 individual UPDATE statements per cycle. Each UPDATE is a separate round-trip to Supabase (which may be in a different region). At ~5-20ms per round-trip, that is **500-2000ms per cycle** just for writes.

**Recommendation**: Use a single batched UPDATE with a VALUES list:

```python
from sqlalchemy import case, literal_column

# Build a single UPDATE ... SET body = CASE WHEN gmail_message_id = X THEN Y ... END
if body_map:
    cases = case(
        *[(Email.gmail_message_id == gid, body) for gid, body in body_map.items()],
        else_=Email.body,
    )
    db.execute(
        update(Email)
        .where(
            Email.account_id == account_id_uuid,
            Email.gmail_message_id.in_(list(body_map.keys())),
        )
        .values(body=cases, updated_at=datetime.utcnow())
    )
```

Or, more efficiently with raw SQL and a temporary VALUES table:

```python
if body_map:
    values_clause = ", ".join(
        f"(:gid_{i}, :body_{i})"
        for i in range(len(body_map))
    )
    params = {}
    for i, (gid, body) in enumerate(body_map.items()):
        params[f"gid_{i}"] = gid
        params[f"body_{i}"] = body

    db.execute(text(f"""
        UPDATE emails e
        SET body = v.body, updated_at = NOW()
        FROM (VALUES {values_clause}) AS v(gmail_message_id, body)
        WHERE e.gmail_message_id = v.gmail_message_id
          AND e.account_id = :account_id
    """), {**params, "account_id": str(account_id_uuid)})
    db.commit()
```

**Estimated improvement**: Reduces write time from 500-2000ms to 50-200ms per cycle (single round-trip). With 15 workers, this saves ~7-27 seconds of cumulative DB wait per minute.

### 5.2 Partial Index on `body IS NULL` (CRITICAL -- Easy Win)

**Current state**: No index exists that efficiently filters for `body IS NULL`.

The query at line 115-124 and the count at lines 227-234 both filter on `Email.body == None`. Without a partial index, these queries scan the full `account_id` index and then filter, which degrades as the backfill progresses.

**Recommendation**: Create this index immediately:

```sql
CREATE INDEX CONCURRENTLY idx_emails_null_body
ON emails (account_id)
WHERE body IS NULL;
```

This index starts large (~1.16M entries) but **shrinks as the backfill progresses**, making the claim query faster over time instead of slower. At 90% completion, the index covers only ~116K rows, making the claim query nearly instant.

**Estimated improvement**: Reduces claim query from 100-500ms to <10ms. With 15 workers running this query every ~5 seconds, that saves ~20-100 seconds of cumulative DB wait per minute.

### 5.3 Unnecessary COUNT(*) Query

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, lines 227-234

```python
remaining = (
    db.query(func.count(Email.id))
    .filter(Email.account_id == account_id, Email.body == None)
    .scalar()
)
```

This COUNT(*) query scans the same rows as the claim query but returns a count instead of rows. It is used solely to decide whether to spawn a replacement worker. This is unnecessary -- if the claim query returned fewer than BATCH_SIZE rows, or if it returned zero rows, the worker can infer whether more work exists.

**Recommendation**: Replace the COUNT with a simpler check:

```python
# Instead of COUNT(*), just check if any NULL rows exist
has_more = (
    db.query(Email.id)
    .filter(Email.account_id == account_id, Email.body == None)
    .limit(1)
    .first()
) is not None
```

With the partial index, this is a single index lookup (~1ms) instead of a full count (~200-1000ms).

### 5.4 Module-Level Engine Creation

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/worker/backfill_body_tasks.py`, line 30

```python
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
```

This creates a **separate** SQLAlchemy engine from the one in `src/core/database.py` (line 13). Each engine has its own connection pool. With `worker_max_tasks_per_child=10`, each Celery child process creates its own engine on import, resulting in 15 separate connection pools.

SQLAlchemy's default `pool_size=5` with `max_overflow=10` means each pool can hold up to 15 connections. With 15 Celery child processes (worst case during restarts, up to 30), that is potentially **225-450 database connections**. Supabase's free tier typically allows 50-100 connections, and the PgBouncer pooler has `max_client_conn=100` (supabase/config.toml line 48).

**Recommendation**: Either reuse the engine from `src/core/database.py`, or explicitly limit the pool:

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=3,
)
```

---

## 6. Concrete Recommendations (Ordered by Impact)

### Recommendation 1: Increase Chunk Size from 20 to 100

**Impact**: ~15-20% throughput increase (~500-700 more emails/min)
**Risk**: Low
**Effort**: 1 line change

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/client.py`, line 231

```python
# Before
chunk_size = 20

# After
chunk_size = 100
```

**Rationale**: The Gmail Batch API supports 100 sub-requests per batch call. Each batch call is a single HTTP request. Increasing from 20 to 100 eliminates 80% of HTTP round-trip overhead. The "concurrent connection limit" concern in the code comment is a misunderstanding -- batch sub-requests do not use separate connections.

**One caveat**: With `BATCH_SIZE=100` in the worker and `chunk_size=100` in the client, each worker makes exactly 1 batch HTTP call per cycle instead of 5. This is optimal. If you also increase BATCH_SIZE (see Recommendation 4), you would make N batch calls per cycle.

---

### Recommendation 2: Add Partial Index on `body IS NULL`

**Impact**: ~10-15% throughput increase, growing over time as backfill progresses
**Risk**: None (CONCURRENTLY avoids locking)
**Effort**: 1 SQL statement

```sql
CREATE INDEX CONCURRENTLY idx_emails_null_body
ON emails (account_id)
WHERE body IS NULL;
```

**Rationale**: The claim query (`WHERE body IS NULL ... FOR UPDATE SKIP LOCKED`) and the remaining-count query both benefit. Without this index, query time grows as the ratio of completed-to-remaining emails increases. At 50% completion, the planner must skip ~580K rows to find NULL ones. At 90% completion, it must skip ~1.04M rows.

---

### Recommendation 3: Batch DB Writes into Single UPDATE

**Impact**: ~8-12% throughput increase
**Risk**: Low
**Effort**: ~20 lines of code

Replace the per-row UPDATE loop at line 182-191 with a single batched UPDATE:

```python
# File: src/worker/backfill_body_tasks.py
# Replace lines 180-210 with:

if body_map:
    # Batched UPDATE using a VALUES join
    values_list = list(body_map.items())
    placeholders = ", ".join(
        f"(:gid_{i}::text, :body_{i}::text)"
        for i in range(len(values_list))
    )
    params = {"account_id": str(account_id_uuid)}
    for i, (gid, body_text) in enumerate(values_list):
        params[f"gid_{i}"] = gid
        params[f"body_{i}"] = body_text

    db.execute(text(f"""
        UPDATE emails e
        SET body = v.body, updated_at = NOW()
        FROM (VALUES {placeholders}) AS v(gmail_message_id, body)
        WHERE e.gmail_message_id = v.gmail_message_id
          AND e.account_id = :account_id
    """), params)

# Handle no-body emails in a single statement (already batched)
no_body_ids = [
    eid for eid, gid in zip(email_ids, gmail_ids)
    if gid not in body_map
]
if no_body_ids:
    db.execute(
        update(Email)
        .where(Email.id.in_(no_body_ids))
        .values(body="", updated_at=datetime.utcnow())
    )

db.commit()
```

---

### Recommendation 4: Increase BATCH_SIZE and Fix Remaining-Count Query

**Impact**: ~5-8% throughput increase
**Risk**: Low
**Effort**: ~10 lines

```python
# File: src/worker/backfill_body_tasks.py

# Increase batch size to reduce claim frequency
BATCH_SIZE = 500  # Was 100

# Replace COUNT(*) remaining query (lines 227-234) with existence check:
has_more = (
    db.query(Email.id)
    .filter(
        Email.account_id == account_id,
        Email.body == None,  # noqa: E711
    )
    .limit(1)
    .first()
) is not None

if has_more:
    backfill_worker.delay(account_id)
```

With chunk_size=100 and BATCH_SIZE=500, each worker cycle makes 5 Gmail batch calls (good pipelining) and reduces the claim query frequency by 5x.

---

### Recommendation 5: Add Sentinel Cleanup Task

**Impact**: Reliability (prevents permanent data loss)
**Risk**: None
**Effort**: ~20 lines

```python
# File: src/worker/backfill_body_tasks.py

@celery_app.task(name="cleanup_stuck_fetching")
def cleanup_stuck_fetching():
    """Reset emails stuck in __fetching__ state for more than 10 minutes."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        result = db.execute(
            update(Email)
            .where(
                Email.body == "__fetching__",
                Email.updated_at < cutoff,
            )
            .values(body=None)
        )
        if result.rowcount > 0:
            logger.warning(f"Reset {result.rowcount} stuck __fetching__ emails")
        db.commit()
    finally:
        db.close()
```

Also fix the sentinel UPDATE to include `updated_at` (line 137):
```python
# Before (line 134-138)
db.execute(
    update(Email)
    .where(Email.id.in_(email_ids))
    .values(body="__fetching__")
)

# After
db.execute(
    update(Email)
    .where(Email.id.in_(email_ids))
    .values(body="__fetching__", updated_at=datetime.utcnow())
)
```

Register the cleanup task in Celery Beat to run every 5 minutes.

---

### Recommendation 6: Rebalance Workers Across Accounts

**Impact**: ~3-5% throughput increase
**Risk**: None
**Effort**: Configuration change

```python
# File: src/worker/backfill_body_tasks.py

# Per-account worker counts based on quota and email volume
WORKERS_CONFIG = {
    "procore-main": 8,    # 1,050,738 emails, 50 msg/sec quota
    "procore-private": 5,  # 87,100 emails, 50 msg/sec quota
    "personal": 2,         # 26,476 emails, 10 msg/sec quota
}
```

Increase Celery concurrency to 15 (already set) or 20 if the Heroku dyno can handle it. The `procore-main` account has 90% of the emails and the same quota as `procore-private`, so it should get more workers.

---

### Recommendation 7: Increase `worker_max_tasks_per_child`

**Impact**: ~1% throughput increase, reduced process restart overhead
**Risk**: None (memory leak risk is low for this workload)
**Effort**: 1 line

```python
# File: src/worker/celery_app.py, line 29
"worker_max_tasks_per_child": 100,  # Was 10
```

With 100 tasks per child, each process restarts every ~10,000 emails instead of every ~1,000. This reduces the frequency of expensive process restarts (which include re-importing all modules and reinitializing the SQLAlchemy engine).

---

### Recommendation 8: Fix Rate Limiter to Return Wait Time

**Impact**: ~3-5% throughput increase (eliminates polling overhead)
**Risk**: Low
**Effort**: ~30 lines

See Section 2.3 for the full implementation sketch. The key change is making the Lua script return the exact wait time needed instead of a boolean, so callers sleep precisely instead of polling in 20ms increments.

---

## 7. Estimated Throughput After Recommendations

| Change | Estimated New Rate | Cumulative |
|--------|-------------------|------------|
| Baseline | 3,400/min | 3,400/min |
| +Rec 1 (chunk_size=100) | +600/min | 4,000/min |
| +Rec 2 (partial index) | +450/min | 4,450/min |
| +Rec 3 (batch writes) | +350/min | 4,800/min |
| +Rec 4 (BATCH_SIZE=500) | +250/min | 5,050/min |
| +Rec 5 (sentinel cleanup) | reliability | 5,050/min |
| +Rec 6 (rebalance workers) | +200/min | 5,250/min |
| +Rec 7 (max_tasks=100) | +50/min | 5,300/min |
| +Rec 8 (rate limiter fix) | +200/min | 5,500/min |

**Projected final throughput: ~5,500 emails/min** (91% of theoretical maximum).

The remaining ~9% gap is inherent overhead: TLS handshake time on Gmail batch calls, PostgreSQL query planning time, network latency between Heroku and Supabase, and Celery's irreducible per-task overhead. To close that last gap, the async rewrite (Section 3.3) would be needed.

---

## 8. Time-to-Completion Estimates

| Scenario | Rate | Time for 1.16M emails |
|----------|------|----------------------|
| Current | 3,400/min | 5.7 hours |
| After Recs 1-4 (easy wins) | ~5,050/min | 3.8 hours |
| After all Recs | ~5,500/min | 3.5 hours |
| Async rewrite (theoretical max) | ~6,000/min | 3.2 hours |

The easy wins (Recs 1-4) can be applied in under an hour and save ~2 hours of wall-clock time. Given the system is already live, I recommend applying those immediately.

---

## 9. Additional Notes

### 9.1 GmailClient Builds Two API Services (Line 54-55)

```python
self.gmail_service = build("gmail", "v1", credentials=self.credentials)
self.people_service = build("people", "v1", credentials=self.credentials)
```

The `build()` call makes an HTTP request to download the API discovery document. For the backfill workload, the People API service is never used. This adds ~200-500ms to every GmailClient initialization. Since each worker creates a new GmailClient per cycle (line 164), this overhead occurs ~11,600 times during the full backfill.

**Recommendation**: Lazy-initialize the People API service, or pass a flag to skip it for backfill-only workers.

### 9.2 `with_retry` Decorator Retries on All Exceptions (Line 248)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/rate_limiter.py`, lines 245-249

```python
retry=retry_if_exception_type((GmailRateLimitExceeded, Exception)),
```

`retry_if_exception_type(Exception)` retries on **all** exceptions including `KeyError`, `TypeError`, `ValueError`, etc. This means a bug in `_parse_message` (e.g., a missing key in the response) will be retried 5 times with exponential backoff instead of failing fast. This wastes up to 4 + 8 + 16 + 32 = 60 seconds per parse bug.

**Recommendation**: Only retry on network/rate-limit errors:

```python
retry=retry_if_exception_type((GmailRateLimitExceeded, HttpError, ConnectionError, TimeoutError)),
```

### 9.3 `print()` Instead of `logger` in Callbacks (Line 264)

**File**: `/Users/tooeycourtemanche/Documents/GitHub/Obsidian/src/integrations/gmail/client.py`, lines 264, 271

```python
print(f"Error fetching message {request_id}: {exception}")
```

These should use the logger for consistency and to be captured by Heroku's log drain.

---

## 10. Summary of Priorities

| Priority | Recommendation | Type | Effort |
|----------|---------------|------|--------|
| P0 | Chunk size 20 -> 100 | Performance | 1 line |
| P0 | Partial index on body IS NULL | Performance | 1 SQL |
| P0 | Batch DB writes | Performance | 20 lines |
| P1 | BATCH_SIZE 100 -> 500 | Performance | 1 line |
| P1 | Sentinel cleanup task | Reliability | 20 lines |
| P1 | Set updated_at on sentinel write | Bug fix | 1 line |
| P2 | Rebalance workers | Performance | Config |
| P2 | Fix rate limiter wait | Performance | 30 lines |
| P2 | Increase max_tasks_per_child | Performance | 1 line |
| P3 | Lazy-init People API | Performance | 5 lines |
| P3 | Fix retry scope | Reliability | 1 line |
| P3 | Replace print() with logger | Hygiene | 2 lines |

The P0 items alone should increase throughput from ~3,400/min to ~5,000/min and can be applied within 30 minutes.

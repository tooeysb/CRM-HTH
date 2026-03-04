# ADR-003: Redis Token Bucket Rate Limiting

## Status
Accepted

## Context
Gmail API enforces a 250 QPS per-user rate limit. With up to 10 parallel workers fetching messages, we need coordinated rate limiting across processes. Local per-process rate limiting would allow the aggregate to exceed the limit.

## Decision
Implement a Redis-backed token bucket with an atomic Lua script:

### Token Bucket Parameters
- **Max tokens**: 40 (conservative, 16% of Gmail's 250 QPS limit)
- **Refill rate**: 40 tokens/second
- **80% safety margin**: Prevents bursts from triggering Gmail's abuse detection

### Lua Script Atomicity
The refill-and-consume operation runs as a single atomic Lua script in Redis:
1. Calculate tokens to add based on elapsed time since last refill
2. Cap at max_tokens
3. If requested tokens available, consume and return success
4. Otherwise return tokens needed and wait time

### Fallback Behavior
If Redis is unavailable (connection error, timeout), the rate limiter falls back to a local `time.sleep(1/rate)` approach. This provides degraded but functional rate limiting for single-worker scenarios.

### Heroku Redis SSL
Heroku Redis uses self-signed certificates and does not provide CA certificates for verification. The `ssl_cert_reqs=CERT_NONE` setting is the documented Heroku pattern for both the Celery broker and direct Redis connections.

## Consequences
- **Distributed coordination**: All workers share the same token bucket via Redis
- **Burst protection**: Conservative limit prevents Gmail abuse detection triggers
- **Graceful degradation**: Local fallback when Redis is down
- **Operational visibility**: Token count and refill rate are queryable for monitoring

## Alternatives Considered
- **Celery rate_limit**: Rejected because it limits task dispatch rate, not API call rate. A single task makes hundreds of API calls.
- **Per-process sleep**: Rejected because 10 workers sleeping independently would allow 10x the intended rate.
- **Redis SETNX semaphore**: Rejected in favor of token bucket because semaphores don't smooth burst patterns.

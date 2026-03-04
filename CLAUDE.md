# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This System Does

Autonomous email processing pipeline that indexes all historical Gmail across 3 accounts (procore-main, procore-private, personal), extracts themes with Claude Haiku, and generates an Obsidian vault with relationship intelligence profiles.

**Scale**: ~1.16M emails processed, ~14,500 bidirectional contacts discovered, dating back to 2005.

## Development Commands

```bash
# Activate venv (Python 3.11)
source venv/bin/activate

# Run API server
venv/bin/uvicorn src.api.main:app --reload

# Run Celery worker
venv/bin/celery -A src.worker.celery_app worker --loglevel=info

# Run migrations (uses asyncpg, PgBouncer-compatible)
venv/bin/alembic upgrade head

# Generate relationship vault (local only)
venv/bin/python generate_vault.py --discover-only      # SQL only, no cost
venv/bin/python generate_vault.py --profile-limit 10   # Test 10 contacts
venv/bin/python generate_vault.py --vault-only          # Regenerate from existing profiles

# Tests
venv/bin/pytest tests/unit/ -v                                        # All unit tests (235+)
venv/bin/pytest tests/unit/api/test_security.py -v                    # Security/auth tests
venv/bin/pytest tests/unit/worker/test_phases.py -v                   # Worker phase tests
venv/bin/pytest tests/unit/api/test_correlation.py -v                 # Correlation ID tests
venv/bin/pytest tests/unit/integrations/gmail/test_rate_limiter.py -v # Single test file

# Linting
venv/bin/black --line-length 100 --check src/ tests/
venv/bin/ruff check src/ tests/
```

## Architecture

```
FastAPI Routers (src/api/routers/)
  → auth, dashboard, scan, draft, crm
  → Uses sync DB sessions (psycopg2)
  → API key auth via X-API-Key header (src/api/middleware/auth.py)
  → Correlation ID middleware (src/api/middleware/correlation.py)

Services (src/services/)
  → theme_detection/  - Claude prompt templates, tag generation
  → relationships/    - Contact discovery, email sampling, AI profiling
  → obsidian/         - Two vault generators (see below)
  → voice/            - Voice profile generation from sent emails
  → gmail/            - Contact merging across accounts

Integrations (src/integrations/)
  → gmail/client.py   - Batched fetching with rate limiting
  → gmail/rate_limiter.py - Redis token bucket with Lua script
  → claude/batch_processor.py - Batch API + sync fallback with prompt caching

Worker (src/worker/)
  → tasks.py          - Thin orchestrator calling phase modules
  → phases/           - email_sync, theme_detection, vault_generation
  → id_first_tasks.py - Parallel ID-first strategy (production)

Models (src/models/)
  → Email, EmailTag, User, GmailAccount, Contact,
    RelationshipProfile, VoiceProfile, EmailQueue, SyncJob
```

## Two Processing Strategies

**Main Orchestration** (`tasks.py`): Single Celery task runs 5 phases sequentially — fetch emails using `before:`/`after:` queries for historical backfill, extract themes, generate vault. Good for development.

**ID-First Parallel** (`id_first_tasks.py`): Phase 1 fetches all message IDs into EmailQueue table, then spawns up to 10 Phase 2 workers that claim batches with `skip_locked=True`. Self-healing: reclaims stale IDs after 15 minutes. 5x faster, used in production.

## Two Vault Generation Systems

**Email-Based** (`vault_manager.py` + `note_generator.py`): Individual Contacts/ and Emails/YYYY/MM/ notes. Generated during Phase 5 of main orchestration (development only, skipped on Heroku).

**Relationship-Based** (`relationship_vault.py`): AI-profiled People/ notes, Thread/ notes grouped by `gmail_thread_id`, and Indexes/ with Dataview dashboards. Run via `generate_vault.py` CLI.

## Key Patterns

**Claude API calls**: Always use prompt caching (`cache_control: {"type": "ephemeral"}` on system prompt). Strip markdown code blocks from JSON responses. Model: `claude-haiku-4-5-20251001`.

**Database sessions**: Sync sessions (`SyncSessionLocal`) for API routes and CLI scripts. Async sessions (`AsyncSessionLocal`) for Celery tasks. PgBouncer requires `statement_cache_size=0` for asyncpg.

**Email deduplication**: `INSERT ON CONFLICT DO NOTHING` on `(account_id, gmail_message_id)` unique constraint.

**Rate limiting**: Redis-backed token bucket with atomic Lua script. Falls back to local sleep-based limiting if Redis unavailable. Conservative 40 QPS (80% margin below 250 QPS Gmail limit).

**Eager loading**: Use `selectinload()` for relationships accessed in loops (e.g., `Email.tags`).

**Authentication**: API key via `X-API-Key` header, validated against `settings.secret_key`. Public endpoints: `/`, `/health`, `/auth/*`, `/dashboard/widget`. Protected: `/crm/*`, `/draft/*`, `/scan/*`, `/dashboard/stats`.

**Correlation IDs**: Every API request gets an `X-Request-ID` (client-supplied or auto-generated). Available in logs via `[request_id]` prefix. Use `request_id_var.get()` from `src.api.middleware.correlation` in async context.

**Logging**: Use `from src.core.logging import get_logger`. Always lazy format: `logger.info("msg %s", var)`. JSON output in production (`APP_ENV=production`). Automatic credential redaction.

## Deployment

- **Production**: Heroku (`crm-hth`) with web + worker + monitor dynos
- **Database**: Supabase PostgreSQL (remote, not local)
- **Queue**: Redis via Heroku addon
- **Vault generation**: Local only (Heroku has read-only filesystem)

```bash
git push heroku master
heroku ps:restart worker --app crm-hth
heroku logs --app crm-hth --dyno worker --tail
```

## Gotchas

- **Email dates**: Timezone stripped from malformed headers (e.g., `+18:00`) before PostgreSQL insert
- **Gmail queries**: Use `in:anywhere` to include INBOX + SENT + all CATEGORY_* labels
- **Alembic env.py**: Must convert `DATABASE_URL` from `postgresql://` to `postgresql+asyncpg://` for migrations
- **recipient_emails field**: Comma-separated string, not array — must parse in Python and handle `"Name <email>"` format
- **Contact discovery**: Bulk queries essential — per-contact queries against remote Supabase are prohibitively slow (14k+ contacts)
- **Long-running DB operations**: Close/refresh sessions after Gmail fetches (2-3 min) to avoid Supabase timeouts. Use `db.merge(obj)` to re-attach detached ORM objects after session reopen.
- **WorkerSessionLocal**: Has `expire_on_commit=False` to prevent DetachedInstanceError in multi-session lifecycle
- **ADRs**: Architecture decisions documented in `docs/adr/`

## Gmail Accounts

| Label | Email | User ID |
|-------|-------|---------|
| procore-main | tooey@procore.com | d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31 |
| procore-private | 2e@procore.com | (same user) |
| personal | tooey@hth-corp.com | (same user) |

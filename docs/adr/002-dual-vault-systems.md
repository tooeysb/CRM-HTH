# ADR-002: Dual Vault Generation Systems

## Status
Accepted

## Context
The system generates an Obsidian vault for relationship intelligence. Two distinct use cases emerged:

1. **During email sync** (Phase 5 of `scan_gmail_task`): Generate simple per-email and per-contact notes for browsing raw data.
2. **Post-processing** (via `generate_vault.py` CLI): Generate AI-profiled relationship notes with thread grouping and Dataview dashboards.

## Decision
Maintain two independent vault generators:

### Email-Based Vault (`vault_manager.py` + `note_generator.py`)
- Runs as Phase 5 of the main scan orchestration
- Generates `Contacts/Name.md` and `Emails/YYYY/MM/Subject.md` notes
- Simple template-based markdown, no AI calls
- Skipped in production (Heroku read-only filesystem)

### Relationship-Based Vault (`relationship_vault.py`)
- Run manually via `generate_vault.py` CLI
- Generates `People/Name.md` with AI relationship summaries from `RelationshipProfile` table
- Groups emails into `Threads/` notes by `gmail_thread_id`
- Creates `Indexes/` with Dataview-powered dashboards (by company, frequency, recency)
- Requires pre-computed relationship profiles (Claude Haiku, ~$2 per 1000 contacts)

## Consequences
- **Separation of concerns**: Sync-time vault is fast/cheap; relationship vault is rich/expensive
- **Two code paths**: Must maintain both, but they share no state beyond the database
- **Local-only**: Both systems write to the local filesystem. Production deployment serves data via API, not vault files.

## Alternatives Considered
- **Single unified vault**: Rejected because the AI profiling step is expensive ($2/1000 contacts) and slow (minutes). Running it during every sync would waste money and block the pipeline.
- **Incremental relationship vault**: Future consideration. Currently regenerates fully each run. Could track `profiled_at` timestamps to only regenerate changed profiles.

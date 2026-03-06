"""
State persistence for LinkedIn enrichment runs.

Tracks which contacts have been processed to support resume after interruption.
Uses a simple JSON file in the project root.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from src.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_STATE_FILE = Path(__file__).parent.parent.parent / ".enrichment_state.json"


@dataclass
class EnrichmentState:
    """Persistent state for the enrichment run."""

    processed_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    last_run_date: str | None = None
    total_enriched: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    _state_file: Path = field(default=DEFAULT_STATE_FILE, repr=False, compare=False)

    def mark_processed(self, contact_id: str):
        if contact_id not in self.processed_ids:
            self.processed_ids.append(contact_id)
            self.total_enriched += 1

    def mark_skipped(self, contact_id: str):
        if contact_id not in self.skipped_ids:
            self.skipped_ids.append(contact_id)
            self.total_skipped += 1

    def mark_error(self):
        self.total_errors += 1

    def is_processed(self, contact_id: str) -> bool:
        return contact_id in self.processed_ids or contact_id in self.skipped_ids

    def reset_if_new_day(self):
        """Clear per-day tracking if this is a new day."""
        today = date.today().isoformat()
        if self.last_run_date != today:
            logger.info("New day detected — resetting daily state")
            self.processed_ids = []
            self.skipped_ids = []
            self.total_enriched = 0
            self.total_skipped = 0
            self.total_errors = 0

    def save(self):
        self.last_run_date = date.today().isoformat()
        data = asdict(self)
        data.pop("_state_file", None)
        self._state_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, state_file: Path | None = None) -> EnrichmentState:
        path = state_file or DEFAULT_STATE_FILE
        if path.exists():
            try:
                data = json.loads(path.read_text())
                state = cls(**data)
                state._state_file = path
                return state
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupt state file — starting fresh")
                state = cls()
                state._state_file = path
                return state
        state = cls()
        state._state_file = path
        return state

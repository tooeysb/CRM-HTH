#!/usr/bin/env python3
"""
Import parsed ENR Top 400 data into the CRM.

Matches ENR entries to existing CRM companies (by rank first, then fuzzy name),
updates their source_data.enr with full ENR metrics, and creates records for
any companies not yet in the CRM.

Usage:
    python -m scripts.enrichment.enr_importer --dry-run     # Preview matches
    python -m scripts.enrichment.enr_importer               # Import for real
    python -m scripts.enrichment.enr_importer --json FILE    # Use custom parsed JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import httpx  # noqa: E402

from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")

# Corporate suffixes to strip for fuzzy matching
STRIP_SUFFIXES = re.compile(
    r",?\s*\b(inc\.?|llc\.?|corp\.?|co\.?|ltd\.?|l\.?p\.?|group|"
    r"& affiliates|& associates|the|cos\.?|company|companies|"
    r"construction|contracting|contractors|enterprises|holdings|"
    r"services|solutions|builders)\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    """Normalize company name for fuzzy matching."""
    n = name.lower().strip()
    # Strip corporate suffixes
    n = STRIP_SUFFIXES.sub("", n)
    # Remove punctuation and collapse whitespace
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    n = " ".join(n.split())
    return n


def load_crm_companies(client: httpx.Client) -> list[dict]:
    """Load all CRM companies (including no-contact ones).

    Uses sort_by=name for deterministic pagination (avoids the NULL-ARR
    ordering issue where companies can be skipped or duplicated).
    """
    all_companies: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    while True:
        resp = client.get(
            "/crm/api/companies",
            params={
                "page": page,
                "page_size": 100,
                "contact_filter": "all",
                "sort_by": "name",
                "sort_dir": "asc",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        for c in data["items"]:
            if c["id"] not in seen_ids:
                all_companies.append(c)
                seen_ids.add(c["id"])
        if page * 100 >= data.get("total", 0):
            break
        page += 1
    return all_companies


def match_entries(
    enr_entries: list[dict], crm_companies: list[dict]
) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """Match ENR entries to CRM companies.

    Returns (matched_pairs, unmatched_entries).
    Each matched pair is (enr_entry, crm_company).
    """
    # Build lookup by rank
    rank_to_crm: dict[int, dict] = {}
    for c in crm_companies:
        sd = c.get("source_data") or {}
        enr = sd.get("enr", {})
        rank = enr.get("rank_2024")
        if rank:
            rank_to_crm[rank] = c

    # Build lookup by normalized name
    name_to_crm: dict[str, dict] = {}
    for c in crm_companies:
        norm = _normalize_name(c["name"])
        if norm:
            name_to_crm[norm] = c

    matched: list[tuple[dict, dict]] = []
    unmatched: list[dict] = []

    for entry in enr_entries:
        rank = entry["rank_2024"]

        # Strategy 1: Match by existing rank
        if rank in rank_to_crm:
            matched.append((entry, rank_to_crm[rank]))
            continue

        # Strategy 2: Fuzzy name match
        enr_norm = _normalize_name(entry["firm_name"])
        best_match = None
        best_score = 0
        matched_ids = {m[1]["id"] for m in matched}

        for crm_norm, crm_company in name_to_crm.items():
            # Skip already-matched companies
            if crm_company["id"] in matched_ids:
                continue

            # Exact normalized match
            if enr_norm == crm_norm:
                best_match = crm_company
                best_score = 100
                break

            # Both names must be non-trivial (at least 3 chars after normalization)
            if len(enr_norm) < 3 or len(crm_norm) < 3:
                continue

            # Check if all words of the shorter name appear in the longer
            enr_words = set(enr_norm.split())
            crm_words = set(crm_norm.split())
            if enr_words and crm_words:
                shorter = enr_words if len(enr_words) <= len(crm_words) else crm_words
                longer = crm_words if len(enr_words) <= len(crm_words) else enr_words
                overlap = shorter & longer
                # Require ALL words of the shorter name to appear AND
                # at least 50% coverage of the longer name
                if (
                    len(overlap) == len(shorter)
                    and len(shorter) >= 2
                    and len(overlap) / len(longer) >= 0.5
                ):
                    score = len(overlap) / len(longer) * 100
                    if score > best_score:
                        best_match = crm_company
                        best_score = score

        if best_match and best_score >= 60:
            matched.append((entry, best_match))
            logger.info(
                "Name match: ENR '%s' → CRM '%s' (score=%d)",
                entry["firm_name"],
                best_match["name"],
                best_score,
            )
        else:
            unmatched.append(entry)

    return matched, unmatched


def build_enr_data(entry: dict) -> dict:
    """Build the source_data.enr dict from a parsed ENR entry."""
    return {
        "rank_2024": entry["rank_2024"],
        "rank_2023": entry["rank_2023"],
        "firm_name": entry["firm_name"],
        "hq_city": entry["hq_city"],
        "hq_state": entry["hq_state"],
        "has_subsidiaries": entry["has_subsidiaries"],
        "revenue_2023_mil": entry["revenue_2023_mil"],
        "intl_revenue_mil": entry["intl_revenue_mil"],
        "new_contracts_2023_mil": entry["new_contracts_2023_mil"],
        "sectors": entry["sectors"],
        "cm_at_risk_pct": entry["cm_at_risk_pct"],
    }


def import_entries(
    matched: list[tuple[dict, dict]],
    unmatched: list[dict],
    client: httpx.Client,
    *,
    dry_run: bool = False,
) -> dict:
    """Update matched companies and create unmatched ones.

    Returns stats dict.
    """
    stats = {"updated": 0, "created": 0, "errors": 0}

    # Update matched companies
    for entry, crm_company in matched:
        enr_data = build_enr_data(entry)
        cid = crm_company["id"]

        # Preserve existing source_data keys, overwrite enr
        existing_sd = crm_company.get("source_data") or {}
        existing_sd["enr"] = enr_data

        if dry_run:
            logger.info(
                "DRY RUN: Would update #%d %s (CRM: %s)",
                entry["rank_2024"],
                entry["firm_name"],
                crm_company["name"],
            )
            stats["updated"] += 1
            continue

        try:
            resp = client.patch(
                f"/crm/api/companies/{cid}",
                json={
                    "source_data": existing_sd,
                    "billing_state": entry["hq_state"],
                    "company_type": "General Contractor",
                },
            )
            resp.raise_for_status()
            stats["updated"] += 1
        except Exception as e:
            logger.error(
                "Failed to update #%d %s: %s", entry["rank_2024"], entry["firm_name"], e
            )
            stats["errors"] += 1

    # Create unmatched companies
    for entry in unmatched:
        enr_data = build_enr_data(entry)

        if dry_run:
            logger.info(
                "DRY RUN: Would create #%d %s, %s, %s",
                entry["rank_2024"],
                entry["firm_name"],
                entry["hq_city"],
                entry["hq_state"],
            )
            stats["created"] += 1
            continue

        try:
            resp = client.post(
                "/crm/api/companies",
                json={
                    "name": entry["firm_name"].title(),
                    "billing_state": entry["hq_state"],
                    "company_type": "General Contractor",
                    "source_data": {"enr": enr_data},
                },
            )
            resp.raise_for_status()
            stats["created"] += 1
            logger.info(
                "Created #%d %s (id=%s)",
                entry["rank_2024"],
                entry["firm_name"],
                resp.json().get("id"),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                logger.warning(
                    "Company already exists: %s — skipping",
                    entry["firm_name"],
                )
            else:
                logger.error(
                    "Failed to create #%d %s: %s",
                    entry["rank_2024"],
                    entry["firm_name"],
                    e,
                )
                stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Import ENR Top 400 data into CRM")
    parser.add_argument(
        "--json",
        default=".enr_parsed.json",
        help="Path to parsed ENR JSON (default: .enr_parsed.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"Parsed JSON not found: {json_path}", file=sys.stderr)
        print("Run the parser first:", file=sys.stderr)
        print("  python -m scripts.enrichment.enr_pdf_parser /path/to/ENR.pdf", file=sys.stderr)
        sys.exit(1)

    with open(json_path) as f:
        enr_entries = json.load(f)

    logger.info("Loaded %d ENR entries from %s", len(enr_entries), json_path)

    from src.core.config import settings  # noqa: E402

    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key — set ENRICHMENT_API_KEY or SECRET_KEY")
        return

    client = httpx.Client(
        base_url=API_BASE,
        headers={"X-API-Key": api_key},
        timeout=30.0,
    )

    try:
        # Load CRM companies
        logger.info("Loading CRM companies...")
        crm_companies = load_crm_companies(client)
        logger.info("Loaded %d CRM companies", len(crm_companies))

        # Match
        matched, unmatched = match_entries(enr_entries, crm_companies)
        logger.info("Matched: %d, Unmatched: %d", len(matched), len(unmatched))

        if unmatched:
            logger.info("Unmatched ENR entries (will be created):")
            for entry in unmatched:
                logger.info(
                    "  #%d %s, %s, %s",
                    entry["rank_2024"],
                    entry["firm_name"],
                    entry["hq_city"],
                    entry["hq_state"],
                )

        # Import
        stats = import_entries(matched, unmatched, client, dry_run=args.dry_run)

        logger.info(
            "Import %s: %d updated, %d created, %d errors",
            "preview" if args.dry_run else "complete",
            stats["updated"],
            stats["created"],
            stats["errors"],
        )

    finally:
        client.close()


if __name__ == "__main__":
    main()
